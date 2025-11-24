from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from core import settings
from .models import File, RateLimitTracker, StorageStats
from .serializers import FileSerializer, StorageStatsSerializer
import os

# Create your views here.
RATE_LIMIT_CALLS = getattr(settings, 'RATE_LIMIT_CALLS', 2)
RATE_LIMIT_WINDOW = getattr(settings, 'RATE_LIMIT_WINDOW', 1)  # seconds
STORAGE_QUOTA_MB = getattr(settings, 'STORAGE_QUOTA_MB', 10)
STORAGE_QUOTA_BYTES = STORAGE_QUOTA_MB * 1024 * 1024

class RateLimitMixin:
    """Mixin to add rate limiting to views"""
    
    def check_rate_limit(self, request):
        """Check if user has exceeded rate limit"""
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        allowed, current_count = RateLimitTracker.check_rate_limit(
            user_id,
            max_calls=RATE_LIMIT_CALLS,
            window_seconds=RATE_LIMIT_WINDOW
        )
        
        if not allowed:
            return Response(
                {'error': 'Call Limit Reached'},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        # Record this call
        RateLimitTracker.record_call(user_id, request.path)
        return None

class FileViewSet( RateLimitMixin, viewsets.ModelViewSet):
    queryset = File.objects.all()
    serializer_class = FileSerializer

    def list(self, request, *args, **kwargs):
        """List files with rate limiting"""
        # Check rate limit
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        user_id = self.request.headers.get('UserId')
        if not user_id:
            return Response({'error': 'User ID is required'}, status=status.HTTP_401_UNAUTHORIZED)

        search = request.query_params.get('search')
        file_type = request.query_params.get('file_type')
        min_size = request.query_params.get('min_size')
        max_size = request.query_params.get('max_size')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        queryset = self.queryset.filter(user_id=user_id)

        if search:
            queryset = queryset.filter(original_filename__icontains=search)
        if file_type:
            queryset = queryset.filter(file_type=file_type)
        if min_size:
            queryset = queryset.filter(size__gte=min_size)
        if max_size:
            queryset = queryset.filter(size__lte=max_size)
        if start_date:
            queryset = queryset.filter(uploaded_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(uploaded_at__lte=end_date)
                
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
            
    def retrieve(self, request, *args, **kwargs):
        """Get file details with rate limiting"""
        # Check rate limit
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        return super().retrieve(request, *args, **kwargs)
    
    #POST /api/files/
    def create(self, request, *args, **kwargs):
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = self.request.headers.get('UserId')
        if not user_id:
            return Response({'error': 'User ID is required'}, status=status.HTTP_401_UNAUTHORIZED)
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        file_hash = File.calculate_file_hash(file_obj)
        file_size = file_obj.size
        existing_file = File.objects.filter(file_hash=file_hash, user_id=user_id, is_reference=False).first()
        if existing_file:
            new_file = File.objects.create(
                file=existing_file.file,
                original_filename=file_obj.name,
                file_type=file_obj.content_type,
                size=file_size,
                user_id=user_id,
                file_hash=file_hash,
                is_reference=True,
                original_file=existing_file
            )
            existing_file.increment_reference_count()
            stats,_= StorageStats.objects.get_or_create(user_id=user_id)
            stats.update_stats()
        else:
            stats,_= StorageStats.objects.get_or_create(user_id=user_id)
            if stats.total_storage_used + file_size > STORAGE_QUOTA_BYTES:
                return Response({'error': 'Storage limit exceeded'}, status=status.HTTP_400_BAD_REQUEST)
            new_file = File.objects.create(
                file=file_obj,
                original_filename=file_obj.name,
                file_type=file_obj.content_type,
                size=file_size,
                user_id=user_id,
                file_hash=file_hash,
                is_reference=False,
                reference_count=0
            )
            stats.update_stats()

        serializer = FileSerializer(new_file)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def destroy(self, request, *args, **kwargs):
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response({'error': 'User ID is required'}, status=status.HTTP_401_UNAUTHORIZED)
        instance = self.get_object()
        if instance.user_id != user_id:
            return Response({'error': 'Unauthorized'}, status=status.HTTP_401_UNAUTHORIZED)
        if instance.is_reference:
            instance.original_file.decrement_reference_count()
            instance.delete()
        else:
            if instance.reference_count > 0:
                return Response({'error': 'Cannot delete this original file while it has references.'}, status=status.HTTP_401_UNAUTHORIZED)
            else:
                if instance.file and os.path.isfile(instance.file.path):
                    os.remove(instance.file.path)
                instance.delete()
        stats,_= StorageStats.objects.get_or_create(user_id=user_id)
        stats.update_stats()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def storage_stats(self, request):
        """Get storage statistics for user"""
        # Check rate limit
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        stats, _ = StorageStats.objects.get_or_create(user_id=user_id)
        stats.update_stats()  # Ensure stats are current
        
        serializer = StorageStatsSerializer(stats)
        return Response(serializer.data)

        
    @action(detail=False, methods=['get'])
    def file_types(self, request):
        """Get list of unique file types for user"""
        # Check rate limit
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        file_types = File.objects.filter(
            user_id=user_id
        ).values_list('file_type', flat=True).distinct().order_by('file_type')
        
        return Response(list(file_types))
