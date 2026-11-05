"""Exercise the real TH2 and product service over localhost HTTP."""
import base64
import importlib.util
import logging
import os
import socket
import subprocess
import time
import uuid
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.serving import make_server
import pymysql
import requests

from order_service.app import create_app

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auth_service'))
spec = importlib.util.spec_from_file_location('lab02_app', ROOT / 'auth_service/app.py')
auth_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth_module)


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        auth = auth_module.create_app({'TESTING': True, 'DATABASE': str(cls.root / 'users.db'),
                                       'JWT_SECRET': 'test-only-secret-' * 4})
        cls.auth_client = auth.test_client()
        cls.auth_server = make_server('127.0.0.1', 0, auth, threaded=True)
        cls.auth_url = f'http://127.0.0.1:{cls.auth_server.server_port}'
        threading.Thread(target=cls.auth_server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.auth_server.server_close)
        cls.addClassCleanup(cls.auth_server.shutdown)
        cls.db_settings = dict(host=os.environ.get('TEST_DB_HOST', '127.0.0.1'),
                               port=int(os.environ.get('TEST_DB_PORT', '3306')),
                               user=os.environ.get('TEST_DB_USER', 'root'),
                               password=os.environ.get('TEST_DB_PASSWORD', ''), autocommit=True)
        cls.test_db = 'lab04_test_' + uuid.uuid4().hex
        with pymysql.connect(**cls.db_settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE `{cls.test_db}` CHARACTER SET utf8mb4')
        cls.addClassCleanup(cls.drop_database)
        with cls.product_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute((ROOT / 'product_service/schema.sql').read_text(encoding='utf-8'))
                cursor.executemany('INSERT INTO products (id,name,description,price,quantity) VALUES (%s,%s,%s,%s,%s)',
                    [(1, 'Ban phim', 'Test fixture', '250000.00', 20), (2, 'Chuot', 'Test fixture', '150000.00', 30),
                     (3, 'Man hinh', 'Test fixture', '2500000.00', 0)])
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.product_url = f'http://127.0.0.1:{port}'
        env = dict(os.environ, DB_HOST=cls.db_settings['host'], DB_PORT=str(cls.db_settings['port']),
                   DB_USER=cls.db_settings['user'], DB_PASSWORD=cls.db_settings['password'],
                   DB_NAME=cls.test_db, AUTH_URL=cls.auth_url + '/auth', TEST_HTTP_PORT=str(port))
        cls.product_process = subprocess.Popen([sys.executable, '-c',
            'import os; from app import create_app; create_app().run(host="127.0.0.1", port=int(os.environ["TEST_HTTP_PORT"]))'],
            cwd=ROOT / 'product_service', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_product)
        for _ in range(100):
            try:
                if requests.get(cls.product_url, timeout=0.3).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            raise RuntimeError('Lab03 did not start')

    @classmethod
    def product_db(cls):
        return pymysql.connect(database=cls.test_db, **cls.db_settings)

    @classmethod
    def stop_product(cls):
        cls.product_process.terminate()
        cls.product_process.wait(timeout=10)

    @classmethod
    def drop_database(cls):
        with pymysql.connect(**cls.db_settings) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'DROP DATABASE `{cls.test_db}`')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def login(self):
        response = self.auth_client.post('/login', json={'userName': 'phat',
            'password': base64.b64encode(b'Phat@123').decode()})
        self.assertEqual(response.status_code, 200)
        return {'Authorization': 'Bearer ' + response.json['access_token']}

    def setUp(self):
        self.path = self.root / (self._testMethodName + '.db')
        self.app = create_app({'TESTING': True, 'DATABASE': str(self.path), 'AUTH_URL': self.auth_url,
            'PRODUCT_URL': self.product_url})
        self.client = self.app.test_client()
        self.headers = self.login()

    def call(self, method, path, **kwargs):
        return self.client.open(path, method=method, headers=self.headers, **kwargs)

    def new(self, items=None):
        return self.call('POST', '/orders', json={'customer_name': 'Nguyen Van A',
            'customer_email': 'a@example.com', 'items': items if items is not None else [{'product_id': 1, 'quantity': 2}]})

    def test_all_ten_routes_and_totals(self):
        created = self.new()
        self.assertEqual(created.status_code, 201)
        order = created.json
        oid, iid = order['id'], order['items'][0]['id']
        self.assertEqual(order['total_amount'], '500000.00')
        self.assertEqual(len(self.call('GET', '/orders').json), 1)
        self.assertEqual(self.call('GET', f'/orders/{oid}').json['id'], oid)
        self.assertEqual(self.call('GET', f'/order_items/{iid}').json['quantity'], 2)
        self.assertEqual(len(self.call('GET', '/order_items').json), 1)
        added = self.call('POST', '/order_items', json={'order_id': oid, 'product_id': 2, 'quantity': 3})
        self.assertEqual(added.status_code, 201)
        self.assertEqual(self.call('GET', f'/orders/{oid}').json['total_amount'], '950000.00')
        updated = self.call('PUT', f'/order_items/{iid}', json={'quantity': 4})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['total_price'], '1000000.00')
        self.assertEqual(self.call('GET', f'/orders/{oid}').json['total_amount'], '1450000.00')
        self.assertEqual(self.call('DELETE', f'/order_items/{added.json["id"]}').status_code, 204)
        self.assertEqual(self.call('GET', f'/orders/{oid}').json['total_amount'], '1000000.00')
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'pending'}).status_code, 200)
        self.assertEqual(self.call('DELETE', f'/orders/{oid}').status_code, 204)
        self.assertEqual(self.call('GET', '/order_items').json, [])
        self.assertEqual(self.call('GET', f'/orders/{oid}').status_code, 404)

    def test_three_services_over_http_with_real_product_crud(self):
        server = make_server('127.0.0.1', 0, self.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}'
        pid = None
        try:
            created = requests.post(self.product_url + '/products', headers=self.headers, timeout=5,
                json={'name': 'HTTP integration', 'description': 'TH3 real product', 'price': '12.34', 'quantity': 5})
            self.assertEqual(created.status_code, 201)
            pid = created.json()['id']
            response = requests.post(url + '/orders', headers=self.headers, timeout=5,
                json={'customer_name': 'HTTP customer', 'customer_email': 'http@example.com',
                      'items': [{'product_id': pid, 'quantity': 3}]})
            self.assertEqual(response.status_code, 201)
            order = response.json()
            self.assertEqual(order['total_amount'], '37.02')
            self.assertEqual(order['items'][0]['product_name'], 'HTTP integration')
            stock = requests.get(self.product_url + f'/products/{pid}', headers=self.headers, timeout=5)
            self.assertEqual(stock.json()['quantity'], 5)
            self.assertEqual(requests.delete(url + f'/orders/{order["id"]}', headers=self.headers, timeout=5).status_code, 204)
        finally:
            if pid is not None:
                requests.delete(self.product_url + f'/products/{pid}', headers=self.headers, timeout=5)
            server.shutdown()
            server.server_close()

    def test_rollback_insufficient_stock_and_missing_product(self):
        for product_id in (3, 999):
            response = self.new([{'product_id': 1, 'quantity': 1}, {'product_id': product_id, 'quantity': 1}])
            self.assertEqual(response.status_code, 409 if product_id == 3 else 404)
            self.assertEqual(self.call('GET', '/orders').json, [])
            self.assertEqual(self.call('GET', '/order_items').json, [])

    def test_auth_missing_forged_revoked_expired(self):
        self.assertEqual(self.client.get('/orders').status_code, 401)
        self.assertEqual(self.client.get('/orders', headers={'Authorization': 'Bearer fake'}).status_code, 401)
        self.login()  # TH2 revokes the preceding token on next login.
        self.assertEqual(self.call('GET', '/orders').status_code, 401)
        self.headers = self.login()
        import jwt
        token = self.headers['Authorization'].split()[1]
        claims = jwt.decode(token, options={'verify_signature': False})
        claims.update(iat=1, exp=2)
        expired = jwt.encode(claims, 'test-only-secret-' * 4, algorithm='HS256')
        self.assertEqual(self.client.get('/orders', headers={'Authorization': 'Bearer ' + expired}).status_code, 401)

    def test_all_business_routes_require_auth(self):
        for method, path in [('GET', '/orders'), ('POST', '/orders'), ('GET', '/orders/1'),
                             ('PUT', '/orders/1'), ('DELETE', '/orders/1'), ('GET', '/order_items'),
                             ('POST', '/order_items'), ('GET', '/order_items/1'),
                             ('PUT', '/order_items/1'), ('DELETE', '/order_items/1')]:
            self.assertEqual(self.client.open(path, method=method).status_code, 401)

    def test_validation_and_duplicates(self):
        for quantity in (0, -1, True, 1.5, '2', 2147483648):
            self.assertEqual(self.new([{'product_id': 1, 'quantity': quantity}]).status_code, 400)
        self.assertEqual(self.new([]).status_code, 400)
        self.assertEqual(self.new([{'product_id': 1, 'quantity': 1, 'unit_price': 0}]).status_code, 400)
        self.assertEqual(self.new([{'product_id': 1, 'quantity': 1}] * 2).status_code, 409)
        self.assertEqual(self.call('GET', '/orders').json, [])
        self.assertEqual(self.call('POST', '/orders', data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.call('GET', '/order_items?order_id=no').status_code, 400)

    def test_terminal_status_and_snapshot_price(self):
        order = self.new().json
        oid, iid = order['id'], order['items'][0]['id']
        changed = requests.put(self.product_url + '/products/1', headers=self.headers,
            json={'name': 'Ban phim', 'description': 'Updated via TH3', 'price': '300000.00', 'quantity': 20}, timeout=5)
        self.assertEqual(changed.status_code, 200)
        try:
            self.assertEqual(self.call('PUT', f'/order_items/{iid}', json={'quantity': 3}).json['unit_price'], '250000.00')
        finally:
            restored = requests.put(self.product_url + '/products/1', headers=self.headers,
                json={'name': 'Ban phim', 'description': 'Test fixture', 'price': '250000.00', 'quantity': 20}, timeout=5)
            self.assertEqual(restored.status_code, 200)
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'completed'}).status_code, 200)
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'pending'}).status_code, 409)
        self.assertEqual(self.call('PUT', f'/order_items/{iid}', json={'quantity': 1}).status_code, 409)
        self.assertEqual(self.call('DELETE', f'/orders/{oid}').status_code, 409)
        self.assertEqual(self.call('DELETE', f'/order_items/{iid}').status_code, 409)
        self.assertEqual(self.call('POST', '/order_items', json={'order_id': oid, 'product_id': 2, 'quantity': 1}).status_code, 409)

    def test_cancel_and_empty_order(self):
        order = self.new().json
        oid = order['id']
        self.call('DELETE', f'/order_items/{order["items"][0]["id"]}')
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'completed'}).status_code, 409)
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'cancelled'}).status_code, 200)
        self.assertEqual(self.call('PUT', f'/orders/{oid}', json={'status': 'cancelled'}).status_code, 200)

    def test_stock_failure_does_not_change_existing_order(self):
        order = self.new().json
        iid = order['items'][0]['id']
        self.assertEqual(self.call('PUT', f'/order_items/{iid}', json={'quantity': 21}).status_code, 409)
        self.assertEqual(self.call('GET', f'/orders/{order["id"]}').json['total_amount'], '500000.00')

    def test_upstream_down_and_malformed_responses(self):
        from urllib.error import URLError
        with patch('order_service.app.urlopen', side_effect=URLError('offline')):
            self.assertEqual(self.call('GET', '/orders').status_code, 503)
        original = self.app.config['PRODUCT_URL']
        self.app.config['PRODUCT_URL'] = self.auth_url
        self.assertEqual(self.new().status_code, 404)
        self.app.config['PRODUCT_URL'] = original
        def bad_remote(base, path):
            return {'authenticated': True} if path == '/auth' else {'name': 'X', 'quantity': 10, 'price': 'NaN'}
        with patch('order_service.app.remote', side_effect=bad_remote):
            self.assertEqual(self.new().status_code, 502)
        self.assertEqual(self.call('GET', '/orders').json, [])

    def test_decimal_arithmetic_and_total_limit(self):
        def fixture_remote(base, path):
            return {'authenticated': True} if path == '/auth' else {'name': 'Decimal', 'quantity': 100, 'price': '0.10'}
        with patch('order_service.app.remote', side_effect=fixture_remote):
            response = self.new([{'product_id': 1, 'quantity': 3}])
            self.assertEqual(response.json['total_amount'], '0.30')
        def expensive_remote(base, path):
            return {'authenticated': True} if path == '/auth' else {'name': 'Expensive', 'quantity': 100, 'price': '60000000.00'}
        with patch('order_service.app.remote', side_effect=expensive_remote):
            self.assertEqual(self.new([{'product_id': 1, 'quantity': 1}, {'product_id': 2, 'quantity': 1}]).status_code, 400)
        self.assertEqual(len(self.call('GET', '/orders').json), 1)


if __name__ == '__main__':
    unittest.main()
