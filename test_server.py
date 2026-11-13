import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dashboard', Path(__file__).with_name('server.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class DashboardTests(unittest.TestCase):
    def setUp(self):
        app.IDLE_CACHE.clear()
        self.target = {'name': 'test', 'provider': 'oci', 'profile': 'A1', 'auth': 'security_token', 'region': 'us-sanjose-1', 'compartment_id': 'ocid1.compartment.oc1..abc', 'instance_id': 'ocid1.instance.oc1..abc'}
    def test_incomplete_configuration_does_not_call_cli(self):
        with patch.object(app, 'call_oci') as call:
            result = app.collect({'provider': 'oci'})
        call.assert_not_called()
        self.assertTrue(result['errors'])
    def test_cloud_metrics_and_instance_status(self):
        def fake(target, args):
            if args[0] == 'compute':
                return {'lifecycle-state': 'RUNNING'}
            return [{'aggregated-datapoints': [{'timestamp': '2026-11-13T00:00:00Z', 'value': 12.3}]}]
        with patch.object(app, 'call_oci', side_effect=fake):
            result = app.collect(self.target)
        self.assertEqual(result['lifecycle'], 'RUNNING')
        self.assertEqual(result['metrics']['cpu'][0]['value'], 12.3)
        self.assertEqual(len(result['metrics']), 6)
        self.assertFalse(result['errors'])
    def test_missing_metrics_and_api_errors_not_zero(self):
        with patch.object(app, 'call_oci', side_effect=RuntimeError('denied')):
            result = app.collect(self.target)
        self.assertEqual(result['lifecycle'], 'UNKNOWN')
        self.assertEqual(result['metrics']['cpu'], [])
        self.assertTrue(result['errors'])

    def test_discovery_accepts_region_hyphens_and_skips_terminated(self):
        values = [
            {'display-name':'A1','id':'ocid1.instance.oc1.us-sanjose-1.abc','lifecycle-state':'RUNNING'},
            {'display-name':'E2','id':'ocid1.instance.oc1.us-sanjose-1.def','lifecycle-state':'RUNNING'},
            {'display-name':'old','id':'ocid1.instance.oc1.us-sanjose-1.xyz','lifecycle-state':'TERMINATED'},
        ]
        with patch.object(app, 'call_oci', return_value=values):
            result = app.discover(self.target)
        self.assertEqual([x['name'] for x in result], ['A1', 'E2'])

    def test_empty_cli_response_is_empty_list(self):
        with patch.object(app.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            self.assertEqual(app.call_oci(self.target, ['events','rule','list']), [])

    def test_metric_queries_use_explicit_time_bounds(self):
        calls = []
        def fake(target, args):
            calls.append(args)
            if args[0] == 'compute':
                return {'lifecycle-state': 'RUNNING'}
            return []
        with patch.object(app, 'call_oci', side_effect=fake):
            app.collect(self.target)
        metric_calls = [args for args in calls if args[:2] == ['monitoring', 'metric-data']]
        self.assertEqual(len(metric_calls), 10)
        self.assertTrue(all('--start-time' in args and '--end-time' in args for args in metric_calls))
        calls.clear()
        with patch.object(app, 'call_oci', side_effect=fake):
            app.collect(self.target)
        metric_calls = [args for args in calls if args[:2] == ['monitoring', 'metric-data']]
        self.assertEqual(len(metric_calls), 8)

    def test_chart_query_validates_controls_and_fetches_both_servers(self):
        t2 = dict(self.target, name='E2', instance_id='ocid1.instance.oc1.us-sanjose-1.other')
        captured = []
        def fake(target, args):
            captured.append(args)
            return [{'aggregated-datapoints': [{'timestamp':'2026-11-13T00:00:00Z','value': 42.0}]}]
        with patch.object(app, 'call_oci', side_effect=fake):
            data = app.chart_data('cpu', '1h', '5m', 'p95', [self.target, t2])
        self.assertEqual(len(data['series']), 2)
        self.assertTrue(all('percentile(0.95)' in args[args.index('--query-text')+1] for args in captured))
        self.assertTrue(all('--start-time' in args and '--end-time' in args for args in captured))
        with self.assertRaises(ValueError):
            app.chart_data('cpu', '1h', '1m', 'mean() malicious', [self.target])
        with self.assertRaises(ValueError):
            app.chart_data('cpu', '7d', '1m', 'mean', [self.target])

    def test_chart_network_always_uses_rate(self):
        with patch.object(app, 'call_oci', return_value=[]) as call:
            data = app.chart_data('network_in', '24h', '5m', 'max', [self.target])
        self.assertEqual(data['statistic'], 'rate')
        args = call.call_args.args[1]
        self.assertIn('.rate()', args[args.index('--query-text')+1])

    def test_chart_historical_end_time_is_used_and_future_rejected(self):
        end = (app.dt.datetime.now(app.dt.timezone.utc)-app.dt.timedelta(days=1)).replace(microsecond=0).isoformat()
        with patch.object(app, 'call_oci', return_value=[]) as call:
            data = app.chart_data('cpu', '1h', '1m', 'mean', [self.target], end)
        args = call.call_args.args[1]
        self.assertEqual(args[args.index('--end-time')+1], end)
        self.assertEqual(data['end'], end)
        future = (app.dt.datetime.now(app.dt.timezone.utc)+app.dt.timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            app.chart_data('cpu', '1h', '1m', 'mean', [self.target], future)

    def test_chart_http_endpoint_returns_json(self):
        from unittest.mock import MagicMock
        handler = MagicMock()
        handler.headers = {'Host':'127.0.0.1:18765'}
        handler.path = '/api/chart?metric=cpu&range=1h&interval=1m&stat=mean'
        handler.wfile = io.BytesIO()
        answer = {'queried_at': app.time.time(), 'series': [{'error':None,'points':[]}]}
        old_targets = app.TARGETS
        try:
            app.TARGETS = [self.target]
            app.CHART_CACHE.clear()
            with patch.object(app, 'chart_data', return_value=answer):
                app.Handler.do_GET(handler)
            handler.send_response.assert_called_once_with(200)
            handler.send_header.assert_any_call('Content-Type', 'application/json; charset=utf-8')
            self.assertIn(b'queried_at', handler.wfile.getvalue())
        finally:
            app.TARGETS = old_targets
            app.CHART_CACHE.clear()

    def test_chart_http_invalid_query_returns_400(self):
        from unittest.mock import MagicMock
        handler = MagicMock()
        handler.headers = {'Host':'127.0.0.1:18765'}
        handler.path = '/api/chart?metric=cpu&range=1h&interval=1m&stat=invalid'
        old_targets = app.TARGETS
        try:
            app.TARGETS = [self.target]
            app.CHART_CACHE.clear()
            app.Handler.do_GET(handler)
            handler.send_error.assert_called_once_with(400)
        finally:
            app.TARGETS = old_targets
            app.CHART_CACHE.clear()

if __name__ == '__main__':
    unittest.main()
