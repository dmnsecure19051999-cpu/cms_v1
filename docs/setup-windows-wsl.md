# Hướng dẫn cài đặt từng bước trên Windows (WSL2 + Ubuntu)

Hướng dẫn này giúp bạn cài Ubuntu trên Windows, cài Docker và chạy pipeline từ đầu trên một máy mới.

---

## Bước 1 — Bật WSL2 và cài Ubuntu

Mở **PowerShell** với quyền **Administrator**, chạy:

```powershell
wsl --install
```

> Lệnh này tự động: bật WSL2, bật Virtual Machine Platform, và cài Ubuntu mới nhất từ Microsoft Store.

**Restart máy** khi được yêu cầu.

Sau khi restart, Ubuntu tự mở và yêu cầu tạo tài khoản:

```
Enter new UNIX username: <tên của bạn, ví dụ: longdh>
New password: <đặt mật khẩu>
Retype new password: <nhập lại>
```

> Nếu Ubuntu không tự mở, tìm **Ubuntu** trong Start Menu và mở thủ công.

---

## Bước 2 — Cập nhật hệ thống và cài Python, Git

Trong terminal Ubuntu:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

Kiểm tra:

```bash
python3 --version   # phải >= 3.10
git --version
```

---

## Bước 3 — Cài Docker Engine

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Sau đó **đóng terminal Ubuntu** và mở lại để group docker có hiệu lực.

---

## Bước 4 — Bật systemd (để Docker tự chạy khi mở Ubuntu)

```bash
sudo tee /etc/wsl.conf > /dev/null <<EOF
[boot]
systemd=true
EOF
```

Quay ra **PowerShell Windows**, chạy:

```powershell
wsl --shutdown
```

Mở lại Ubuntu, rồi bật Docker tự động:

```bash
sudo systemctl enable docker
sudo systemctl start docker
docker ps   # nếu ra bảng trống là OK
```

---

## Bước 5 — Cài VS Code và kết nối WSL

1. Tải và cài [Visual Studio Code](https://code.visualstudio.com) trên Windows.

2. Mở VS Code → **Extensions** (`Ctrl+Shift+X`) → tìm **WSL** (tác giả Microsoft) → Install.

   Hoặc chạy trong PowerShell:
   ```powershell
   code --install-extension ms-vscode-remote.remote-wsl
   ```

3. Trong terminal Ubuntu, chạy:
   ```bash
   code .
   ```
   VS Code sẽ tự mở và kết nối vào môi trường WSL — thanh dưới góc trái hiển thị **WSL: Ubuntu**.

---

## Bước 6 — Lấy code project về máy

```bash
cd ~
git clone <repo-url> cms
```

Hoặc copy folder `cms/` thủ công (ví dụ qua USB):

```
# Đường dẫn ổ C: trong Ubuntu là /mnt/c/
cp -r /mnt/c/Users/<tên-windows>/Desktop/cms ~/cms
```

---

## Bước 7 — Chạy setup project

```bash
cd ~/cms
bash setup.sh
```

Script sẽ:
- Tạo `.venv` và cài requirements
- Tạo `.env` từ `.env.example`
- Hỏi có muốn start PostgreSQL qua Docker không → nhập `y`
- Test kết nối database

---

## Bước 8 — Cấu hình `.env`

Mở file `.env` và điền đường dẫn thực tế đến 3 thư mục dữ liệu:

```bash
nano .env
```

```env
# Ví dụ: SharePoint sync vào thư mục trên ổ C
CANCEL_DIR=/mnt/c/Users/<tên-windows>/SharePoint/cancel
CUSTOMER_DATA_DIR=/mnt/c/Users/<tên-windows>/SharePoint/customer_data
REVENUE_DIR=/mnt/c/Users/<tên-windows>/SharePoint/revenue

DB_HOST=localhost
DB_PORT=5433
DB_NAME=cms_db
DB_USER=postgres
DB_PASSWORD=your_password
```

> **Lưu ý:** Trong WSL, ổ `C:\` của Windows được mount tại `/mnt/c/`.  
> Nhấn `Ctrl+O` để lưu, `Ctrl+X` để thoát nano.

---

## Bước 9 — Chạy pipeline

```bash
# Lần đầu — load toàn bộ dữ liệu
.venv/bin/python -m loader.main --mode init

# Hàng ngày — chỉ load file mới
.venv/bin/python -m loader.main --mode daily
```

Log hiển thị trực tiếp trên terminal và được lưu tại `logs/`.

---

## Tóm tắt nhanh

```
PowerShell (Admin): wsl --install  →  Restart
Ubuntu: apt install python3 git
Ubuntu: curl -fsSL https://get.docker.com | sh
Ubuntu: /etc/wsl.conf → systemd=true
PowerShell: wsl --shutdown  →  Mở lại Ubuntu
Ubuntu: systemctl enable docker
Windows: cài VS Code + ext WSL
Ubuntu: git clone <repo> cms && cd cms && bash setup.sh
Ubuntu: nano .env  →  điền đường dẫn + DB
Ubuntu: .venv/bin/python -m loader.main --mode init
```

---

## Xử lý sự cố thường gặp

**`wsl --install` báo lỗi**
→ Vào **Control Panel → Programs → Turn Windows features on or off** → bật **Windows Subsystem for Linux** và **Virtual Machine Platform** → Restart.

**`docker: permission denied`**
→ Chưa đăng xuất/vào lại sau khi `usermod`. Đóng terminal Ubuntu và mở lại.

**`docker ps` báo `Cannot connect to the Docker daemon`**
→ Docker chưa chạy. Chạy: `sudo systemctl start docker`

**Không thấy file SharePoint trong `/mnt/c/`**
→ SharePoint sync phải đang chạy trên Windows. Kiểm tra trong File Explorer xem folder đã sync chưa (biểu tượng ✓ xanh).

**VS Code không kết nối WSL**
→ Đảm bảo đã cài extension **WSL** (không phải Remote SSH). Thử lại lệnh `code .` trong Ubuntu.
