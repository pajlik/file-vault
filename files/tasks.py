"""
Background tasks for processing files with AI
Use Celery or Django-Q for async processing
"""
from django.utils import timezone
from .models import File, FileMetadata
from .ai_service import AIFileProcessor
import logging

logger = logging.getLogger(__name__)


def process_file_with_ai(file_id: str):
    """
    Background task to process a file with AI
    This should be called asynchronously after file upload
    
    Usage with Celery:
    @shared_task
    def process_file_with_ai(file_id: str):
        ...
    
    Usage with Django-Q:
    from django_q.tasks import async_task
    async_task('app.tasks.process_file_with_ai', file_id)
    """
    try:
        file_obj = File.objects.get(id=file_id)
        
        # Skip if already processed
        if file_obj.ai_processed:
            logger.info(f"File {file_id} already processed, skipping")
            return
        
        # Skip if it's a reference (use original file's metadata)
        if file_obj.is_reference and file_obj.original_file:
            if hasattr(file_obj.original_file, 'metadata'):
                # Copy metadata from original
                original_metadata = file_obj.original_file.metadata
                FileMetadata.objects.create(
                    file=file_obj,
                    summary=original_metadata.summary,
                    category=original_metadata.category,
                    subcategory=original_metadata.subcategory,
                    tags=original_metadata.tags,
                    entities=original_metadata.entities,
                    key_info=original_metadata.key_info,
                    confidence_score=original_metadata.confidence_score
                )
                file_obj.ai_processed = True
                file_obj.ai_processed_at = timezone.now()
                file_obj.save()
                logger.info(f"Copied metadata from original file for {file_id}")
                return
        
        # Initialize AI processor
        processor = AIFileProcessor()
        
        # Process the file
        file_path = file_obj.file.path
        metadata = processor.process_file(
            file_obj=file_obj.file,
            file_path=file_path,
            file_type=file_obj.file_type,
            original_filename=file_obj.original_filename
        )
        
        # Save metadata
        FileMetadata.objects.create(
            file=file_obj,
            summary=metadata['summary'],
            category=metadata['category'],
            subcategory=metadata['subcategory'],
            tags=metadata['tags'],
            entities=metadata['entities'],
            key_info=metadata['key_info'],
            confidence_score=metadata['confidence_score']
        )
        
        # Mark as processed
        file_obj.ai_processed = True
        file_obj.ai_processed_at = timezone.now()
        file_obj.save()
        
        logger.info(f"Successfully processed file {file_id} with AI")
        
    except File.DoesNotExist:
        logger.error(f"File {file_id} not found")
    except Exception as e:
        logger.error(f"Error processing file {file_id}: {str(e)}")
        # Mark as failed
        try:
            file_obj = File.objects.get(id=file_id)
            file_obj.ai_processing_failed = True
            file_obj.save()
        except:
            pass


def batch_process_unprocessed_files(user_id: str = None, limit: int = 10):
    """
    Process multiple unprocessed files in batch
    Useful for processing existing files or catching up on failed processing
    """
    query = File.objects.filter(ai_processed=False, ai_processing_failed=False)
    
    if user_id:
        query = query.filter(user_id=user_id)
    
    files = query[:limit]
    
    processed_count = 0
    for file_obj in files:
        try:
            process_file_with_ai(str(file_obj.id))
            processed_count += 1
        except Exception as e:
            logger.error(f"Error in batch processing file {file_obj.id}: {str(e)}")
    
    logger.info(f"Batch processed {processed_count} files")
    return processed_count