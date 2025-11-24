# File Vault APIs 🗄️

A production-ready Django REST API for intelligent file storage with automatic deduplication, storage quota management, and rate limiting. Built to efficiently handle file uploads while preventing duplicate storage and managing user quotas.

## ✨ Key Features

### 🔄 Smart Deduplication
- Automatic hash-based file deduplication (SHA-256)
- Reference counting system for shared files
- Physical file stored only once, multiple logical references
- Significant storage savings for duplicate files

### 📊 Storage Management
- Configurable storage quota per user (default: 10MB)
- Real-time storage statistics tracking
- Separate tracking for original vs deduplicated storage
- Automatic quota enforcement on uploads

### 🚦 Rate Limiting
- Configurable rate limiting (default: 2 requests per second)
- Per-user request tracking
- Prevents API abuse
- Returns meaningful error messages when limit exceeded

### 🔍 Advanced Search & Filtering
- Search files by name
- Filter by file type
- Filter by size range (min/max)
- Filter by date range (start/end date)
- Combine multiple filters

### 🛡️ Robust File Management
- Handles file uploads with multipart/form-data
- Secure file deletion with reference counting
- Only deletes physical files when all references are removed
- Automatic cleanup of orphaned files

## 🏗️ Architecture

### File Deduplication Flow

```
User uploads file → Calculate SHA-256 hash → Check if hash exists
    │
    ├─ Hash exists (Duplicate)
    │   ├─ Create reference record
    │   ├─ Point to existing physical file
    │   ├─ Increment reference count
    │   └─ Update logical storage only
    │
    └─ Hash doesn't exist (New file)
        ├─ Save physical file to disk
        ├─ Create original file record
        ├─ Check storage quota
        └─ Update both original & logical storage
```

### Storage Tracking

- **Original Storage Used**: Physical disk space consumed
- **Logical Storage Used**: Total if all files were stored separately
- **Space Saved**: Logical - Original (deduplication savings)

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Django 4.2+
- Django REST Framework 3.14+

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/pajlik/file-vault.git
cd file-vault
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure settings** (optional)

Edit `backend/settings.py` or set environment variables:

```python
# Rate Limiting
RATE_LIMIT_CALLS = 2  # requests per window
RATE_LIMIT_WINDOW = 1  # seconds

# Storage Quota
STORAGE_QUOTA_MB = 10  # MB per user
```

5. **Run migrations**
```bash
python manage.py migrate
```

6. **Start development server**
```bash
python manage.py runserver
```

Server will start at `http://localhost:8000`

## 📡 API Endpoints

### Base URL: `/api/files/`

All requests require a `UserId` header for authentication.

### 1. Upload File
```http
POST /api/files/
Headers: UserId: user123
Content-Type: multipart/form-data

Body:
  file: [binary file data]
```

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "file_url": "/media/uploads/user123/abc123.pdf",
  "original_filename": "document.pdf",
  "file_type": "application/pdf",
  "size": 102400,
  "uploaded_at": "2024-11-24T10:30:00Z",
  "user_id": "user123",
  "file_hash": "abc123def456...",
  "is_reference": false,
  "reference_count": 0
}
```

### 2. List Files
```http
GET /api/files/
Headers: UserId: user123

Query Parameters (optional):
  - search: Search by filename
  - file_type: Filter by MIME type
  - min_size: Minimum file size in bytes
  - max_size: Maximum file size in bytes
  - start_date: Filter files uploaded after this date (YYYY-MM-DD)
  - end_date: Filter files uploaded before this date (YYYY-MM-DD)
```

**Example:**
```http
GET /api/files/?search=report&file_type=application/pdf&min_size=1000
```

**Response (200 OK):**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "file_url": "/media/uploads/user123/report.pdf",
    "original_filename": "Q3_Report.pdf",
    "file_type": "application/pdf",
    "size": 204800,
    "uploaded_at": "2024-11-24T10:30:00Z",
    "is_reference": false,
    "reference_count": 2
  }
]
```

### 3. Get File Details
```http
GET /api/files/{id}/
Headers: UserId: user123
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "file_url": "/media/uploads/user123/document.pdf",
  "original_filename": "document.pdf",
  "file_type": "application/pdf",
  "size": 102400,
  "uploaded_at": "2024-11-24T10:30:00Z",
  "user_id": "user123",
  "file_hash": "abc123...",
  "is_reference": true,
  "reference_count": 0,
  "original_file": "440e8400-e29b-41d4-a716-446655440001"
}
```

### 4. Delete File
```http
DELETE /api/files/{id}/
Headers: UserId: user123
```

**Behavior:**
- If file is a reference: Deletes reference, decrements original's count
- If file is original with references: Deletes record, file remains for references
- If file is original with no references: Deletes both record and physical file

**Response (204 No Content)**

### 5. Get Storage Statistics
```http
GET /api/files/storage_stats/
Headers: UserId: user123
```

**Response (200 OK):**
```json
{
  "user_id": "user123",
  "total_files": 15,
  "original_storage_used": 5242880,
  "logical_storage_used": 15728640,
  "space_saved": 10485760,
  "storage_quota": 10485760,
  "storage_used_percentage": 50.0,
  "last_updated": "2024-11-24T10:30:00Z"
}
```

### 6. Get File Types
```http
GET /api/files/file_types/
Headers: UserId: user123
```

**Response (200 OK):**
```json
[
  "application/pdf",
  "image/jpeg",
  "image/png",
  "text/plain"
]
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Django Settings
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Rate Limiting
RATE_LIMIT_CALLS=2
RATE_LIMIT_WINDOW=1

# Storage Quota (in MB)
STORAGE_QUOTA_MB=10

# Database (for production)
DATABASE_URL=postgresql://user:password@localhost:5432/filedb
```

### Settings.py Configuration

```python
# Rate Limiting
RATE_LIMIT_CALLS = int(os.getenv('RATE_LIMIT_CALLS', 2))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', 1))

# Storage Quota
STORAGE_QUOTA_MB = int(os.getenv('STORAGE_QUOTA_MB', 10))
```

## 📊 Database Schema

### UploadedFile Model
```python
- id: UUIDField (Primary Key)
- file: FileField
- original_filename: CharField
- file_type: CharField
- size: BigIntegerField
- uploaded_at: DateTimeField
- user_id: CharField
- file_hash: CharField (SHA-256)
- is_reference: BooleanField
- original_file: ForeignKey (self, nullable)
- reference_count: IntegerField
```

### StorageStats Model
```python
- user_id: CharField (Primary Key)
- total_files: IntegerField
- original_storage_used: BigIntegerField
- logical_storage_used: BigIntegerField
- space_saved: BigIntegerField
- last_updated: DateTimeField
```

### RateLimitTracker Model
```python
- user_id: CharField
- endpoint: CharField
- timestamp: DateTimeField
```

## 🧪 Testing with Postman

### 1. Upload a File

```
Method: POST
URL: http://localhost:8000/api/files/
Headers:
  - UserId: test_user_123
Body: form-data
  - file: [Select your file]
```

### 2. Upload the Same File Again (Tests Deduplication)

```
Same as above - observe that is_reference=true in response
```

### 3. List Files with Search

```
Method: GET
URL: http://localhost:8000/api/files/?search=document&file_type=application/pdf
Headers:
  - UserId: test_user_123
```

### 4. Get Storage Stats

```
Method: GET
URL: http://localhost:8000/api/files/storage_stats/
Headers:
  - UserId: test_user_123
```

### 5. Delete a File

```
Method: DELETE
URL: http://localhost:8000/api/files/{file_id}/
Headers:
  - UserId: test_user_123
```

## 🐛 Error Responses

### 400 Bad Request
```json
{
  "error": "No file provided"
}
```

### 401 Unauthorized
```json
{
  "error": "UserId header is required"
}
```

### 403 Forbidden
```json
{
  "error": "Permission denied"
}
```

### 429 Too Many Requests
```json
{
  "error": "Call Limit Reached"
}
```
or
```json
{
  "error": "Storage Quota Exceeded"
}
```

## 📁 Project Structure

```
file-vault/
├── backend/
│   ├── settings.py          # Django settings
│   ├── urls.py              # URL routing
│   └── wsgi.py              # WSGI config
├── files/
│   ├── models.py            # Database models
│   ├── serializers.py       # DRF serializers
│   ├── views.py             # API views
│   ├── urls.py              # App URLs
│   └── migrations/          # Database migrations
├── media/
│   └── uploads/             # Uploaded files storage
├── manage.py                # Django management
├── requirements.txt         # Python dependencies
├── .gitignore              # Git ignore rules
└── README.md               # This file
```

## 🔐 Security Considerations

1. **Authentication**: Currently uses simple `UserId` header. For production, implement JWT or OAuth2.

2. **File Validation**: Add file type and size validation before upload.

3. **Path Traversal**: Django's FileField handles this, but validate filenames.

4. **CORS**: Configure CORS headers for frontend integration.

5. **HTTPS**: Always use HTTPS in production.

## 🚀 Production Deployment

### Switch to PostgreSQL

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'filedb',
        'USER': 'dbuser',
        'PASSWORD': 'password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

### Use Cloud Storage (AWS S3)

```python
# Install: pip install django-storages boto3

DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_STORAGE_BUCKET_NAME = 'your-bucket-name'
AWS_S3_REGION_NAME = 'us-east-1'
AWS_ACCESS_KEY_ID = 'your-access-key'
AWS_SECRET_ACCESS_KEY = 'your-secret-key'
```

### Deploy with Gunicorn

```bash
pip install gunicorn
gunicorn backend.wsgi:application --bind 0.0.0.0:8000
```

### Use Redis for Rate Limiting (Recommended)

```python
# Install: pip install django-redis

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 👤 Author

**Prajwal** ([@pajlik](https://github.com/pajlik))

## 🙏 Acknowledgments

- Built with Django and Django REST Framework
- Inspired by modern cloud storage solutions
- Deduplication algorithm based on SHA-256 hashing

## 📞 Support

If you have any questions or issues, please open an issue on GitHub.

---

**Happy File Storing! 🎉**