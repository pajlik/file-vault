from rest_framework import serializers
from .models import File, StorageStats

class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ['id', 'file', 'original_filename', 'file_type', 'size', 'uploaded_at',   
            'user_id',
            'file_hash',
            'reference_count',
            'is_reference',
            'original_file']
        read_only_fields = [            
            'id',
            'original_file',] 


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
