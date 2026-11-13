#!/usr/bin/env python3
"""Local read-only OCI dashboard. Credentials remain in OCI CLI configuration."""
import datetime as dt
import configparser
import concurrent.futures
import math
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.json'
DATA = {'status': 'starting', 'servers': []}
LOCK = threading.Lock()
IDLE_CACHE = {}
IDLE_CACHE_LOCK = threading.Lock()
TARGETS = []
CHART_CACHE = {}
CHART_LOCK = threading.Lock()
OCI_SEMAPHORE = threading.BoundedSemaphore(4)
RANGES = {'1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800}
INTERVALS = {'1m': 60, '5m': 300, '1h': 3600, '1d': 86400}
STATS = {'mean': 'mean()', 'min': 'min()', 'max': 'max()', 'sum': 'sum()', 'count': 'count()', 'rate': 'rate()', 'p50': 'percentile(0.5)', 'p90': 'percentile(0.9)', 'p95': 'percentile(0.95)', 'p99': 'percentile(0.99)', 'p999': 'percentile(0.999)'}
# The names for the network counters differ in Oracle's metric documentation.
METRICS = {'cpu': ('CpuUtilization', 'mean'), 'memory': ('MemoryUtilization', 'mean'),
           'network_in': ('NetworksBytesIn', 'rate'), 'network_out': ('NetworksBytesOut', 'rate'),
           'disk_read': ('DiskBytesRead', 'rate'), 'disk_write': ('DiskBytesWritten', 'rate')}


def call_oci(target, args):
    command = [os.environ.get('OCI_CLI_BIN', 'oci'), *args, '--profile', target['profile'],
               '--region', target['region'], '--auth', target['auth'], '--output', 'json',
               '--no-retry', '--connection-timeout', '8', '--read-timeout', '20']
    with OCI_SEMAPHORE:
        result = subprocess.run(command, capture_output=True, text=True, timeout=35, check=False)
    if result.returncode:
        raise RuntimeError('OCI 查询失败：请检查身份认证、区域和只读 IAM 权限。')
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout).get('data')


def valid(t):
    return (t.get('provider') == 'oci' and t.get('auth') in ('api_key', 'security_token')
            and re.fullmatch(r'ocid1\.(?:compartment|tenancy)\.[a-z0-9.-]+', t.get('compartment_id', ''))
            and re.fullmatch(r'ocid1\.instance\.[a-z0-9.-]+', t.get('instance_id', ''))
            and re.fullmatch(r'[a-z0-9-]+', t.get('region', ''))
            and re.fullmatch(r'[A-Za-z0-9_-]+', t.get('profile', '')))


def collect(t):
    result = {'name': t.get('name', 'OCI'), 'provider': 'OCI', 'region': t.get('region', ''), 'metrics': {}, 'history': {}, 'errors': []}
    if not valid(t):
        result['errors'].append('配置不完整：请填写 region、compartment_id 和 instance_id。')
        return result
    try:
        instance = call_oci(t, ['compute', 'instance', 'get', '--instance-id', t['instance_id']])
        result['lifecycle'] = instance.get('lifecycle-state', 'UNKNOWN')
        result['shape'] = instance.get('shape', '')
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError):
        result['lifecycle'] = 'UNKNOWN'
        result['errors'].append('无法读取实例状态：请检查 CLI 登录、区域和权限。')
    try:
        plugins = call_oci(t, ['instance-agent', 'plugin', 'list', '--compartment-id', t['compartment_id'], '--instanceagent-id', t['instance_id'], '--all']) or []
        plugin = next((p for p in plugins if p.get('name') == 'Compute Instance Monitoring'), None)
        result['monitoring_plugin'] = plugin.get('status', 'UNKNOWN') if plugin else 'UNKNOWN'
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        result['monitoring_plugin'] = 'UNKNOWN'
        result['errors'].append('监控插件状态查询失败。')
    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(minutes=15)).isoformat()
    for key, (metric, stat) in METRICS.items():
        query = f'{metric}[1m]{{resourceId = "{t["instance_id"]}"}}.{stat}()'
        try:
            series = call_oci(t, ['monitoring', 'metric-data', 'summarize-metrics-data', '--compartment-id', t['compartment_id'], '--namespace', 'oci_computeagent', '--query-text', query, '--start-time', start, '--end-time', now.isoformat()]) or []
            points = [p for s in series for p in (s.get('aggregated-datapoints') or []) if p.get('value') is not None]
            points.sort(key=lambda p: p.get('timestamp', ''))
            result['metrics'][key] = points[-168:]
        except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError):
            result['metrics'][key] = []
            result['errors'].append(f'{metric} 查询失败或无权限。')
    for key in ('cpu', 'memory'):
        metric, stat = METRICS[key]
        query = f'{metric}[1h]{{resourceId = "{t["instance_id"]}"}}.{stat}()'
        try:
            series = call_oci(t, ['monitoring', 'metric-data', 'summarize-metrics-data', '--compartment-id', t['compartment_id'], '--namespace', 'oci_computeagent', '--query-text', query, '--start-time', (now - dt.timedelta(days=7)).isoformat(), '--end-time', now.isoformat()]) or []
            points = [p for s in series for p in (s.get('aggregated-datapoints') or []) if p.get('value') is not None]
            points.sort(key=lambda p: p.get('timestamp', ''))
            result['history'][key] = points[-168:]
        except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError):
            result['history'][key] = []
            result['errors'].append(f'{metric} 七天历史查询失败或无权限。')
    cache_key = (t['profile'], t['region'], t['instance_id'])
    with IDLE_CACHE_LOCK:
        cached = IDLE_CACHE.get(cache_key)
    if cached and time.time() - cached['collected_at'] < 3600:
        result['idle_reference'] = dict(cached)
        return result
    result['idle_reference'] = {'status': 'unknown', 'network_utilization': None, 'official_decision': None, 'collected_at': time.time()}
    idle_ok = True
    for key in ('cpu', 'memory'):
        metric, stat = METRICS[key]
        query = f'{metric}[1m]{{resourceId = "{t["instance_id"]}"}}.{stat}()'
        try:
            # Keep the window within the OCI one-minute-resolution maximum of seven days.
            start = now - dt.timedelta(days=7) + dt.timedelta(minutes=1)
            series = call_oci(t, ['monitoring', 'metric-data', 'summarize-metrics-data', '--compartment-id', t['compartment_id'], '--namespace', 'oci_computeagent', '--query-text', query, '--start-time', start.isoformat(), '--end-time', now.isoformat()]) or []
            points = [p for s in series for p in (s.get('aggregated-datapoints') or []) if p.get('value') is not None]
            values = sorted(p['value'] for p in points)
            result['idle_reference'][key + '_samples'] = len(values)
            if values:
                result['idle_reference'][key + '_mean'] = sum(values) / len(values)
                if key == 'cpu':
                    result['idle_reference']['cpu_minute_mean_p95'] = values[max(0, math.ceil(len(values) * .95) - 1)]
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
            idle_ok = False
            result['errors'].append(f'{metric} 七天分钟采样查询失败，闲置参考未知。')
    if idle_ok:
        with IDLE_CACHE_LOCK:
            IDLE_CACHE[cache_key] = dict(result['idle_reference'])
    return result


def rows(data):
    return data.get('items', []) if isinstance(data, dict) else (data or [])


def discover(t):
    """Find resources in the configured compartment; preserve configured fallback on error."""
    items = rows(call_oci(t, ['compute', 'instance', 'list', '--compartment-id', t['compartment_id'], '--all']))
    targets = []
    for item in items:
        if item.get('lifecycle-state') == 'TERMINATED':
            continue
        entry = dict(t, name=item.get('display-name', 'OCI'), instance_id=item.get('id', ''), compartment_id=item.get('compartment-id', t['compartment_id']))
        if valid(entry):
            targets.append(entry)
    return targets


def account_services(t):
    """Read usage and audit; no OCI writes and no secret material returned."""
    result = {'usage': [], 'cost': [], 'alarms': [], 'events': [], 'event_rules': 0, 'errors': [], 'coverage': '当前配置的隔间和区域'}
    config = configparser.ConfigParser()
    config.read(Path.home() / '.oci' / 'config')
    try:
        tenant = config[t['profile']]['tenancy']
        now = dt.datetime.now(dt.timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        usage = ['usage-api', 'usage-summary', 'request-summarized-usages', '--tenant-id', tenant,
                 '--granularity', 'DAILY', '--time-usage-started', start.isoformat(), '--time-usage-ended', end.isoformat(),
                 '--group-by', '["service","skuName","skuPartNumber","unit"]', '--is-aggregate-by-time', 'true', '--limit', '1000']
        for key, kind in [('usage', 'USAGE'), ('cost', 'COST')]:
            try:
                data = rows(call_oci(t, usage + ['--query-type', kind]))
                result[key] = [{k: x.get(k) for k in ('service', 'sku-name', 'sku-part-number', 'unit', 'computed-quantity', 'computed-amount', 'currency', 'time-usage-started', 'time-usage-ended')} for x in data]
                if len(data) >= 1000:
                    result['errors'].append('用量结果可能存在更多分页，请勿视为完整账单。')
            except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
                result['errors'].append(('用量' if key == 'usage' else '费用') + '查询失败，请检查账单权限。')
        result['billing_period_start'] = start.isoformat()
        result['billing_query_end'] = end.isoformat()
    except (KeyError, configparser.Error):
        result['errors'].append('无法读取 OCI 租户配置。')
    try:
        a = rows(call_oci(t, ['monitoring', 'alarm-status', 'list-alarms-status', '--compartment-id', t['compartment_id'], '--all']))
        result['alarms'] = [{k:x.get(k) for k in ('display-name','status','severity','timestamp-triggered')} for x in a]
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        result['errors'].append('告警状态查询失败。')
    try:
        result['event_rules'] = len(rows(call_oci(t, ['events', 'rule', 'list', '--compartment-id', t['compartment_id'], '--all'])))
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        result['event_rules'] = None
        result['errors'].append('事件规则查询失败。')
    try:
        now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
        events = rows(call_oci(t, ['audit', 'event', 'list', '--compartment-id', t['compartment_id'], '--start-time', (now-dt.timedelta(days=1)).isoformat(), '--end-time', now.isoformat(), '--all']))
        selected = [x for x in events if any(word in str(x.get('event-type', '')).lower() for word in ('instance','compute'))]
        result['events'] = [{k:x.get(k) for k in ('event-time','event-type')} for x in selected[-20:]]
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        result['errors'].append('审计事件查询失败。')
    return result


def chart_data(metric, span, interval, statistic, targets, end_time=None):
    """Run only allowlisted queries for already-discovered instances."""
    if metric not in METRICS or span not in RANGES or interval not in INTERVALS or statistic not in STATS:
        raise ValueError('不支持的查询选项')
    if RANGES[span] > 21600 and interval == '1m' and span != '24h':
        raise ValueError('7 天范围请选择 5 分钟或更长间隔，以控制查询量')
    current = dt.datetime.now(dt.timezone.utc)
    if end_time:
        try:
            now = dt.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('结束时间格式无效')
        if now.tzinfo is None:
            raise ValueError('结束时间缺少时区')
        now = now.astimezone(dt.timezone.utc)
        if now > current + dt.timedelta(minutes=1) or now - dt.timedelta(seconds=RANGES[span]) < current - dt.timedelta(days=90):
            raise ValueError('结束时间超出可查询范围')
    else:
        now = current
    start = now - dt.timedelta(seconds=RANGES[span])
    actual_stat = statistic if metric in ('cpu', 'memory') else 'rate'
    metric_name = METRICS[metric][0]
    def query_one(t):
        result = {'name': t.get('name', 'OCI'), 'points': [], 'error': None}
        query = f'{metric_name}[{interval}]{{resourceId = "{t["instance_id"]}"}}.{STATS[actual_stat]}'
        try:
            data = call_oci(t, ['monitoring', 'metric-data', 'summarize-metrics-data', '--compartment-id', t['compartment_id'], '--namespace', 'oci_computeagent', '--query-text', query, '--start-time', start.isoformat(), '--end-time', now.isoformat()]) or []
            result['points'] = sorted((p for s in data for p in s.get('aggregated-datapoints', []) if isinstance(p.get('value'), (int, float))), key=lambda x:x['timestamp'])
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, KeyError, TypeError):
            result['error'] = '指标查询失败，请检查监控权限和连接。'
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        series = list(pool.map(query_one, targets[:20]))
    return {'metric': metric, 'range': span, 'interval': interval, 'statistic': actual_stat, 'start': start.isoformat(), 'end': now.isoformat(), 'queried_at': time.time(), 'series': series}


def worker():
    global DATA, TARGETS
    while True:
        try:
            config = json.loads(CONFIG.read_text())
            targets = config.get('targets', [])
            expanded = []
            errors = []
            for t in targets[:20]:
                try:
                    found = discover(t) if valid(t) else []
                    expanded.extend(found or [t])
                except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
                    expanded.append(t)
                    errors.append('实例自动发现失败，显示已配置目标。')
            unique = {(t.get('profile'), t.get('region'), t.get('instance_id')): t for t in expanded}
            with LOCK:
                TARGETS = [t for t in list(unique.values())[:20] if valid(t)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                servers = list(pool.map(collect, list(unique.values())[:20]))
            accounts = []
            seen = set()
            for t in targets[:20]:
                account = (t.get('profile'), t.get('region'), t.get('compartment_id'))
                if account not in seen and valid(t):
                    seen.add(account)
                    accounts.append(account_services(t))
            data = {'status': 'ready' if servers else 'unconfigured', 'servers': servers, 'accounts': accounts, 'errors': errors, 'updated': time.time()}
        except (OSError, ValueError, TypeError):
            data = {'status': 'unconfigured', 'servers': [], 'updated': time.time()}
        with LOCK:
            DATA = data
        time.sleep(300 if data['status'] == 'ready' else 5)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Host') not in ('127.0.0.1:18765', 'localhost:18765'):
            self.send_error(403)
            return
        url = urlsplit(self.path)
        if url.path == '/api/status':
            with LOCK:
                body = json.dumps(DATA, ensure_ascii=False).encode()
            mime = 'application/json; charset=utf-8'
        elif url.path == '/api/chart':
            params = parse_qs(url.query)
            metric = params.get('metric', ['cpu'])[0]
            span = params.get('range', ['1h'])[0]
            interval = params.get('interval', ['1m'])[0]
            statistic = params.get('stat', ['mean'])[0]
            end_time = params.get('end', [None])[0]
            with LOCK:
                targets = [dict(t) for t in TARGETS]
            if not targets:
                self.send_error(503)
                return
            key = (metric, span, interval, statistic, end_time, tuple((t['profile'], t['region'], t['instance_id']) for t in targets))
            try:
                with CHART_LOCK:
                    cached = CHART_CACHE.get(key)
                    if not cached or time.time() - cached['queried_at'] >= 45:
                        cached = chart_data(metric, span, interval, statistic, targets, end_time)
                        if all(s['error'] is None for s in cached['series']):
                            if len(CHART_CACHE) >= 30:
                                CHART_CACHE.clear()
                            CHART_CACHE[key] = cached
                body = json.dumps(cached, ensure_ascii=False).encode()
                mime = 'application/json; charset=utf-8'
            except ValueError:
                self.send_error(400)
                return
        elif url.path == '/chart.js':
            body = (ROOT / 'chart.js').read_bytes()
            mime = 'application/javascript; charset=utf-8'
        elif url.path == '/':
            body = (ROOT / 'index.html').read_bytes()
            mime = 'text/html; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    print('服务器看板：http://127.0.0.1:18765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 18765), Handler).serve_forever()
