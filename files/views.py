from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action

from core import settings
from .models import File, RateLimitTracker, StorageStats, FileMetadata
from .serializers import FileSerializer, StorageStatsSerializer, FileMetadataSerializer
from .ai_service import AIFileProcessor
import os

# For async processing - adjust based on your task queue
# from .tasks import process_file_with_ai
# OR for sync processing:
from django.utils import timezone

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
        """List files with rate limiting and AI-powered filtering"""
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
     
        # AI-powered filters
        category = request.query_params.get('category')
        tag = request.query_params.get('tag')
        ai_processed_only = request.query_params.get('ai_processed') == 'true'

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
        if category:
            queryset = queryset.filter(metadata__category=category)
        if tag:
            queryset = queryset.filter(metadata__tags__contains=[tag])
        if ai_processed_only:
            queryset = queryset.filter(ai_processed=True)
                
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
            if hasattr(existing_file, 'metadata'):
                original_metadata = existing_file.metadata
                FileMetadata.objects.create(
                    file=new_file,
                    summary=original_metadata.summary,
                    category=original_metadata.category,
                    subcategory=original_metadata.subcategory,
                    tags=original_metadata.tags,
                    entities=original_metadata.entities,
                    key_info=original_metadata.key_info,
                    confidence_score=original_metadata.confidence_score
                )
                new_file.ai_processed = True
                new_file.ai_processed_at = timezone.now()
                new_file.save()
            
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
            
            # Process with AI asynchronously
            # For production, use: async_task('app.tasks.process_file_with_ai', str(new_file.id))
            # For development/demo, process synchronously:
            try:
                processor = AIFileProcessor()
                file_path = new_file.file.path
                metadata = processor.process_file(
                    file_obj=new_file.file,
                    file_path=file_path,
                    file_type=new_file.file_type,
                    original_filename=new_file.original_filename
                )
                
                FileMetadata.objects.create(
                    file=new_file,
                    summary=metadata['summary'],
                    category=metadata['category'],
                    subcategory=metadata['subcategory'],
                    tags=metadata['tags'],
                    entities=metadata['entities'],
                    key_info=metadata['key_info'],
                    confidence_score=metadata['confidence_score']
                )
                
                new_file.ai_processed = True
                new_file.ai_processed_at = timezone.now()
                new_file.save()
            except Exception as e:
                print(f"AI processing error: {str(e)}")
                new_file.ai_processing_failed = True
                new_file.save()

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
                return Response(
                    {'error': 'Cannot delete this original file while it has references.'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
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
        stats.update_stats()
        
        serializer = StorageStatsSerializer(stats)
        return Response(serializer.data)


    @action(detail=False, methods=['get'])
    def file_types(self, request):
        """Get list of unique file types for user"""
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
    
    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get list of AI-detected categories for user's files"""
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        categories = FileMetadata.objects.filter(
            file__user_id=user_id
        ).values_list('category', flat=True).distinct().order_by('category')
        
        return Response(list(categories))
    
    @action(detail=False, methods=['get'])
    def tags(self, request):
        """Get all unique tags from user's files"""
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get all metadata with tags
        all_metadata = FileMetadata.objects.filter(
            file__user_id=user_id
        ).values_list('tags', flat=True)
        
        # Flatten and deduplicate tags
        all_tags = set()
        for tags_list in all_metadata:
            if tags_list:
                all_tags.update(tags_list)
        
        return Response(sorted(list(all_tags)))
    
    @action(detail=False, methods=['post'])
    def smart_search(self, request):
        """Semantic search across files using AI"""
        rate_limit_response = self.check_rate_limit(request)
        if rate_limit_response:
            return rate_limit_response
        
        user_id = request.headers.get('UserId')
        if not user_id:
            return Response(
                {'error': 'UserId header is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        query = request.data.get('query')
        if not query:
            return Response(
                {'error': 'Query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get user's files with metadata
        files_with_metadata = File.objects.filter(
            user_id=user_id,
            ai_processed=True
        ).select_related('metadata')
        
        if not files_with_metadata.exists():
            return Response([])
        
        # Prepare data for AI
        files_data = []
        for file_obj in files_with_metadata:
            if hasattr(file_obj, 'metadata'):
                files_data.append({
                    'file_id': str(file_obj.id),
                    'filename': file_obj.original_filename,
                    'category': file_obj.metadata.category,
                    'summary': file_obj.metadata.summary,
                    'tags': file_obj.metadata.tags
                })
        
        # Perform semantic search
        processor = AIFileProcessor()
        results = processor.semantic_search(query, files_data)
        if not results:
            return Response({
                'message': 'No relevant files found for your query',
                'results': []
            })
    

        
        # Return matching files
        if results:
            file_ids = [r['file_id'] for r in results]
            files = File.objects.filter(id__in=file_ids)
            
            # Preserve order from AI results
            files_dict = {str(f.id): f for f in files}
            ordered_files = [files_dict[fid] for fid in file_ids if fid in files_dict]
            
            serializer = FileSerializer(ordered_files, many=True, context={'request': request})
            
            # Add relevance scores
            response_data = []
            for i, file_data in enumerate(serializer.data):
                result = next((r for r in results if r['file_id'] == file_data['id']), None)
                if result:
                    file_data['relevance_score'] = result.get('relevance_score', 0)
                    file_data['match_reason'] = result.get('reason', '')
                response_data.append(file_data)
            
            return Response(response_data)
        
        return Response([])