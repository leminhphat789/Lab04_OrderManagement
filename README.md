# Bài thực hành 4 — Order Management

Dịch vụ quản lý đơn hàng theo kiến trúc **SOA**, xây dựng bằng **Python và Flask**. Dịch vụ hỗ trợ tạo, xem, cập nhật trạng thái, xóa đơn hàng và quản lý chi tiết đơn hàng qua REST API.

## Kiến trúc

| Dịch vụ | Địa chỉ mặc định | Cơ sở dữ liệu | Chức năng |
|---|---|---|---|
| TH2 — Authentication | `http://127.0.0.1:5001` | SQLite | Đăng nhập, xác thực JWT |
| TH3 — Product Management | `http://127.0.0.1:5002` | MySQL/MariaDB | Quản lý sản phẩm, cung cấp giá và tồn kho |
| TH4 — Order Management | `http://127.0.0.1:5003` | SQLite | Quản lý đơn hàng và chi tiết đơn hàng |

TH4 gọi `GET /auth` của TH2 để xác thực và `GET /products/{id}` của TH3 để kiểm tra sản phẩm. Mỗi dịch vụ chạy trên cổng riêng, sử dụng database riêng; TH4 không truy cập trực tiếp database của TH2 hoặc TH3.

## Chức năng

- Tạo đơn hàng gồm thông tin khách hàng và danh sách sản phẩm.
- Kiểm tra số lượng đặt so với trường `quantity` do TH3 trả về.
- Lưu tên và giá sản phẩm tại thời điểm thêm vào đơn hàng.
- Tự tính tiền từng mặt hàng và tổng tiền đơn hàng.
- Cập nhật trạng thái: `pending`, `completed`, `cancelled`.
- Thêm, sửa số lượng và xóa chi tiết đơn hàng.
- Từ chối token không hợp lệ, sản phẩm không tồn tại hoặc không đủ tồn kho.
- Rollback toàn bộ thao tác tạo đơn nếu có mặt hàng không hợp lệ.

**Phạm vi:** bài cung cấp backend REST API, kiểm thử bằng Postman. Chỉ kiểm tra tồn kho, chưa giữ hàng hoặc trừ/hoàn kho. Chỉ cho sửa hoặc xóa đơn và chi tiết khi đơn còn `pending`; đơn đã hoàn tất hoặc hủy không được mở lại.

## Cấu trúc thư mục

```text
Lab04_OrderManagement/
├── auth_service/                  # Dịch vụ xác thực TH2
├── product_service/               # Dịch vụ sản phẩm TH3
├── order_service/                 # Dịch vụ đơn hàng TH4 và schema.sql
├── instance/                      # Thư mục dữ liệu runtime, Git chỉ lưu .gitkeep
├── tests/                         # Kiểm thử tích hợp
├── Lab04.postman_collection.json   # Request và assertions cho Postman
├── run.ps1                        # Chạy từng dịch vụ trên Windows
└── README.md
```

## Chạy bài

Mở **ba cửa sổ PowerShell** tại thư mục dự án, mỗi cửa sổ chạy một dịch vụ:

```powershell
# Cửa sổ 1 — TH2, cổng 5001
.\.venv\Scripts\python.exe auth_service/app.py
```

```powershell
# Cửa sổ 2 — TH3, cổng 5002
.\.venv\Scripts\python.exe product_service/app.py
```

```powershell
# Cửa sổ 3 — TH4, cổng 5003
.\.venv\Scripts\python.exe -m order_service.app
```

Có thể dùng `powershell -ExecutionPolicy Bypass -File run.ps1 auth`, `products` hoặc `orders` thay cho lệnh tương ứng sau khi cài thư viện.

Kiểm tra TH4: mở [http://127.0.0.1:5003/health](http://127.0.0.1:5003/health). Kết quả:

```json
{"service":"orders","status":"ok"}
```

`/health` chỉ kiểm tra tiến trình TH4. Các API nghiệp vụ cần TH2 hoạt động; thao tác kiểm tra sản phẩm cần cả TH3 và MySQL.

Nếu dùng địa chỉ khác, đặt `ORDER_AUTH_URL` (URL gốc TH2) và `PRODUCT_URL` (URL gốc TH3) trước khi chạy TH4. Ví dụ:

```powershell
$env:ORDER_AUTH_URL = 'http://127.0.0.1:5001'
$env:PRODUCT_URL = 'http://127.0.0.1:5002'
```

## Danh sách API TH4

Tất cả API dưới đây yêu cầu header `Authorization: Bearer <access_token>`.

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/orders` | Danh sách đơn hàng |
| GET | `/orders/{id}` | Chi tiết đơn và các mặt hàng |
| POST | `/orders` | Tạo đơn, kiểm tra tồn kho |
| PUT | `/orders/{id}` | Cập nhật trạng thái đơn |
| DELETE | `/orders/{id}` | Xóa đơn pending và chi tiết liên quan |
| GET | `/order_items` | Danh sách chi tiết, có thể lọc `?order_id=1` |
| GET | `/order_items/{id}` | Xem một chi tiết đơn |
| POST | `/order_items` | Thêm sản phẩm vào đơn pending |
| PUT | `/order_items/{id}` | Sửa số lượng sản phẩm |
| DELETE | `/order_items/{id}` | Xóa chi tiết và tính lại tổng tiền |

Ví dụ tạo đơn bằng `POST http://127.0.0.1:5003/orders`:

```json
{
  "customer_name": "Nguyễn Văn A",
  "customer_email": "a@example.com",
  "items": [
    {"product_id": 1, "quantity": 2}
  ]
}
```

Thay `product_id` bằng ID tồn tại trong TH3. Tên, giá và tổng tiền do backend xác định; client không tự truyền giá. Giá tiền trong phản hồi là chuỗi có hai chữ số thập phân.

## Kiểm tra bằng Postman

1. Import `Lab04.postman_collection.json`.
2. Chạy **01 — Đăng nhập TH2** để lấy và tự lưu token.
3. Chạy **01.1–01.3** để tạo sản phẩm demo qua TH3 và tự lưu ID.
4. Chạy các request tiếp theo để tạo, xem, sửa, xóa đơn và chi tiết đơn hàng.
5. Kiểm tra cập nhật trạng thái, chặn xóa đơn completed, thiếu tồn kho và thiếu JWT.

Tài khoản mẫu TH2: **`phat` / `Phat@123`**. Request đăng nhập gửi password dạng Base64 theo quy ước TH2:

```json
{"userName":"phat","password":"UGhhdEAxMjM="}
```

Token mặc định có hạn 900 giây. Đăng nhập lại làm token trước đó bị thu hồi. Bộ Postman tự lưu token mới; chạy lại từ request đăng nhập nếu token hết hạn.

| HTTP | Ý nghĩa |
|---|---|
| 200 | Đọc/cập nhật thành công |
| 201 | Tạo thành công |
| 204 | Xóa thành công, không có body |
| 400 | Dữ liệu đầu vào không hợp lệ |
| 401 | Thiếu token, token sai/hết hạn/bị thu hồi |
| 404 | Không tìm thấy đơn, chi tiết hoặc sản phẩm |
| 409 | Thiếu tồn kho hoặc vi phạm quy tắc trạng thái |
| 502 / 503 | Lỗi dịch vụ phụ thuộc hoặc dịch vụ/database không sẵn sàng |

## Kiểm thử tự động

Bật MySQL trước khi chạy. Test dùng database riêng tên `lab04_test_<uuid>` và xóa database test khi hoàn tất; tài khoản test cần quyền tạo/xóa database. Mặc định dùng `127.0.0.1:3306`, user `root`, mật khẩu trống. Có thể cấu hình bằng `TEST_DB_HOST`, `TEST_DB_PORT`, `TEST_DB_USER`, `TEST_DB_PASSWORD`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Test tự chạy TH2 và TH3 trên cổng tạm, kiểm tra đủ 10 API TH4, xác thực, tồn kho, tổng tiền, rollback và trạng thái đơn hàng.

## Các bài liên quan

- [TH2 — Lab02_JWT](https://github.com/leminhphat789/Lab02_JWT)
- [TH3 — Lab03_Product](https://github.com/leminhphat789/Lab03_Product)

Mã TH2 và TH3 được kèm trong repository để thuận tiện chạy và kiểm tra toàn bộ luồng bài thực hành.
