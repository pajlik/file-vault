from rest_framework import serializers
from .models import File, FileMetadata, StorageStats

class FileMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileMetadata
        fields = [
            'summary', 'category', 'subcategory', 'tags', 
            'entities', 'key_info', 'confidence_score',
            'created_at', 'updated_at'
        ]


class FileSerializer(serializers.ModelSerializer):
    metadata = FileMetadataSerializer(read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        model = File
        fields = [
            'id', 'file_url', 'original_filename', 'file_type', 
            'size', 'uploaded_at', 'file_hash', 'is_reference',
            'reference_count', 'ai_processed', 'ai_processed_at',
            'metadata'
        ]
        read_only_fields = ['id', 'original_file', 'uploaded_at', 'file_hash', 'ai_processed', 'ai_processed_at']
    
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and hasattr(obj.file, 'url'):
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


class StorageStatsSerializer(serializers.ModelSerializer):
    """Serializer for storage statistics""" 
    class Meta:
        model = StorageStats
        fields = [
            'total_storage_used',
            'original_storage_used',
            'storage_savings',
            'savings_percentage'
        ]
