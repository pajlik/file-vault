from django.utils import timezone
from django.db import models
import uuid
import os
import hashlib

from django.utils.timezone import timedelta

def file_upload_path(instance, filename):
    """Generate file path for new file upload"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join('uploads', filename)

class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=file_upload_path)
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    size = models.BigIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    user_id = models.CharField(max_length=255, db_index=True)
    file_hash = models.CharField(max_length=64, db_index=True)
    is_reference = models.BooleanField(default=False)
    original_file = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='references')
    reference_count = models.IntegerField(default=0)
    
    # AI-powered fields
    ai_processed = models.BooleanField(default=False, db_index=True)
    ai_processing_failed = models.BooleanField(default=False)
    ai_processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'uploaded_files'
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['user_id', 'uploaded_at']),
            models.Index(fields=['file_hash', 'user_id']),
            models.Index(fields=['file_type']),
            models.Index(fields=['user_id', 'ai_processed']),
        ]

    def __str__(self):
        return self.original_filename
    
    @staticmethod
    def calculate_file_hash(file_obj):
        hasher = hashlib.sha256()
        for obj in file_obj.chunks():
            hasher.update(obj)
        return hasher.hexdigest()
    
    def increment_reference_count(self):
        self.reference_count += 1
        self.save(update_fields=['reference_count'])

    def decrement_reference_count(self):
        self.reference_count = max(0, self.reference_count - 1)
        self.save(update_fields=['reference_count'])


class FileMetadata(models.Model):
    """AI-generated metadata for files"""
    file = models.OneToOneField(File, on_delete=models.CASCADE, related_name='metadata', primary_key=True)
    
    # Core metadata
    summary = models.TextField(blank=True)
    category = models.CharField(max_length=100, db_index=True, blank=True)
    subcategory = models.CharField(max_length=100, blank=True)
    
    # Extracted information
    tags = models.JSONField(default=list, blank=True)
    entities = models.JSONField(default=dict, blank=True)
    key_info = models.JSONField(default=dict, blank=True)
    
    # Semantic search support - UPDATED FIELDS
    embedding = models.JSONField(null=True, blank=True)  # Changed from 'embedding'
    embedding_model = models.CharField(max_length=100, default='all-MiniLM-L6-v2', blank=True)  # NEW
    embedding_computed_at = models.DateTimeField(null=True, blank=True)  # NEW
    
    # Confidence scores
    confidence_score = models.FloatField(default=0.0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'file_metadata'
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Metadata for {self.file.original_filename}"

class StorageStats(models.Model):
    user_id = models.CharField(max_length=255, db_index=True)
    original_storage_used = models.BigIntegerField(default=0)
    total_storage_used = models.BigIntegerField(default=0)
    file_count = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'storage_stats'
        verbose_name_plural = 'Storage Statistics'
    
    def __str__(self):
        return f"Storage for {self.user_id}"
    
    @property
    def storage_savings(self):
        """Calculate bytes saved through deduplication"""
        return self.original_storage_used - self.total_storage_used
    
    @property
    def savings_percentage(self):
        """Calculate percentage of storage saved"""
        if self.original_storage_used == 0:
            return 0.0
        return round((self.storage_savings / self.original_storage_used) * 100, 2)
    
    def update_stats(self):
        files = File.objects.filter(user_id=self.user_id)
        self.original_storage_used = sum(file.size for file in files)
        self.total_storage_used = sum(file.size for file in files if not file.is_reference)
        self.file_count = files.count()
        self.save()
    

class RateLimitTracker(models.Model):
    user_id = models.CharField(max_length=255, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    endpoint = models.CharField(max_length=255)
    class Meta:
        db_table = 'rate_limit_tracker'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user_id', 'timestamp']),
        ]
    
    def __str__(self):
        return f"Rate limit for {self.user_id} at {self.timestamp}"

    @classmethod
    def cleanup_old_records(cls, seconds=60):
        """Remove tracking records older than specified seconds"""
        cutoff = timezone.now() - timezone.timedelta(seconds=seconds)
        cls.objects.filter(timestamp__lt=cutoff).delete()
    
    @classmethod
    def check_rate_limit(cls, user_id, max_calls=2, window_seconds=1):
        """
        Check if user has exceeded rate limit
        Returns: (allowed: bool, current_count: int)
        """
        cutoff = timezone.now() - timezone.timedelta(seconds=window_seconds)
        count = cls.objects.filter(
            user_id=user_id,
            timestamp__gte=cutoff
        ).count()
        
        return count < max_calls, count
    
    @classmethod
    def record_call(cls, user_id, endpoint):
        """Record an API call for rate limiting"""
        cls.objects.create(user_id=user_id, endpoint=endpoint)
        # Cleanup old records periodically
        if cls.objects.count() % 100 == 0:
            cls.cleanup_old_records()