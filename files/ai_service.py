"""
AI Service for processing files and extracting metadata using Claude API
"""
import anthropic
import os
import json
import PyPDF2
import docx
from PIL import Image
import io
import base64
from typing import Dict, Any, Optional, List
from django.conf import settings
from dotenv import load_dotenv  # Add this import
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
# Add this at the top of the file
load_dotenv()  # Load .env file


class AIFileProcessor:
    """Process files using Claude API to extract metadata and insights"""
    
    CATEGORIES = [
        "Work Documents",
        "Personal Documents", 
        "Financial Documents",
        "Legal Documents",
        "Medical Records",
        "Receipts & Invoices",
        "Contracts & Agreements",
        "Educational Materials",
        "Creative Content",
        "Technical Documentation",
        "Travel Documents",
        "Tax Documents",
        "Property Documents",
        "Insurance Documents",
        "Other"
    ]
    
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = "claude-sonnet-4-20250514"
        try:
            self.embedding_model = SentenceTransformer('all-mpnet-base-v2')
        except Exception as e:
            print(f"Warning: Could not load embedding model: {e}")
            self.embedding_model = None
    
    
    def compute_embedding(self, text: str) -> Optional[List[float]]:
        """Compute embedding vector for text"""
        if not self.embedding_model or not text:
            return None
        
        try:
            embedding = self.embedding_model.encode(text)
            return embedding.tolist()  # Convert numpy array to list for JSON
        except Exception as e:
            print(f"Error computing embedding: {e}")
            return None
    
    def process_file(self, file_obj, file_path: str, file_type: str, original_filename: str) -> Dict[str, Any]:
        """
        Main entry point for processing any file type
        Returns metadata dict with category, tags, summary, entities, etc.
        """
        try:
            # Extract text/content based on file type
            content = self._extract_content(file_path, file_type)
            
            if not content:
                return self._get_default_metadata("Unable to extract content from file")
            
            # Use Claude to analyze the content
            metadata = self._analyze_with_claude(content, original_filename, file_type)
            
            # ADD THIS: Compute embedding from summary
            if metadata.get('summary'):
                metadata['embedding'] = self.compute_embedding(metadata['summary'])
            
            return metadata
            
        except Exception as e:
            print(f"Error processing file: {str(e)}")
            return self._get_default_metadata(f"Processing failed: {str(e)}")
    
    def _extract_content(self, file_path: str, file_type: str) -> Optional[str]:
        """Extract text content from various file types"""
        
        # PDF files
        if 'pdf' in file_type.lower():
            return self._extract_from_pdf(file_path)
        
        # Word documents
        elif 'word' in file_type.lower() or file_type.endswith('docx'):
            return self._extract_from_docx(file_path)
        
        # Text files
        elif 'text' in file_type.lower() or file_type in ['text/plain', 'text/csv', 'text/markdown']:
            return self._extract_from_text(file_path)
        
        # Images - use for OCR or visual analysis
        elif 'image' in file_type.lower():
            return self._extract_from_image(file_path)
        
        # For other file types, use filename and type as context
        else:
            return None
    
    def _extract_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF"""
        try:
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                # Limit to first 10 pages to avoid token limits
                max_pages = min(10, len(pdf_reader.pages))
                for page_num in range(max_pages):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
            
            # Limit text length
            return text[:15000]  # ~4k tokens
        except Exception as e:
            print(f"PDF extraction error: {str(e)}")
            return ""
    
    def _extract_from_docx(self, file_path: str) -> str:
        """Extract text from Word document"""
        try:
            doc = docx.Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text[:15000]
        except Exception as e:
            print(f"DOCX extraction error: {str(e)}")
            return ""
    
    def _extract_from_text(self, file_path: str) -> str:
        """Extract text from plain text files"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                return file.read()[:15000]
        except Exception as e:
            print(f"Text extraction error: {str(e)}")
            return ""
    
    def _extract_from_image(self, file_path: str) -> str:
        """For images, we'll send them to Claude for visual analysis"""
        # Return a marker that indicates we should use image analysis
        return f"[IMAGE_FILE:{file_path}]"
    
    def _analyze_with_claude(self, content: str, filename: str, file_type: str) -> Dict[str, Any]:
        """Use Claude to analyze content and extract metadata"""
        
        # Check if this is an image
        if content.startswith("[IMAGE_FILE:"):
            return self._analyze_image_with_claude(content.replace("[IMAGE_FILE:", "").replace("]", ""), filename)
        
        prompt = f"""Analyze this file and extract structured metadata. The filename is "{filename}" and file type is "{file_type}".

Available categories (choose the MOST appropriate one):
{json.dumps(self.CATEGORIES, indent=2)}

File content:
{content}

Provide your analysis in the following JSON format:
{{
  "category": "one of the categories from the list above",
  "subcategory": "more specific classification (optional)",
  "summary": "brief 2-3 sentence summary of the file's content and purpose",
  "tags": ["relevant", "searchable", "keywords", "up to 10"],
  "entities": {{
    "people": ["names of people mentioned"],
    "organizations": ["companies, institutions mentioned"],
    "locations": ["places mentioned"],
    "dates": ["important dates in YYYY-MM-DD format if possible"]
  }},
  "key_info": {{
    "document_type": "specific type like invoice, contract, report, etc.",
    "amount": "any monetary amount if applicable",
    "date": "main document date if found",
    "parties": ["parties involved in contracts/agreements"],
    "any_other_relevant_fields": "extract format-specific important data"
  }},
  "confidence_score": 0.0 to 1.0
}}

IMPORTANT: Respond ONLY with valid JSON. Do not include any markdown formatting or explanations."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse the response
            response_text = response.content[0].text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            
            metadata = json.loads(response_text)
            
            # Validate and clean metadata
            return self._validate_metadata(metadata)
            
        except Exception as e:
            print(f"Claude analysis error: {str(e)}")
            return self._get_default_metadata(f"Analysis failed: {str(e)}")
    
    def _analyze_image_with_claude(self, image_path: str, filename: str) -> Dict[str, Any]:
        """Analyze image files using Claude's vision capabilities"""
        try:
            # Read and encode image
            with open(image_path, 'rb') as img_file:
                image_data = base64.b64encode(img_file.read()).decode('utf-8')
            
            # Detect image type
            img = Image.open(image_path)
            image_format = img.format.lower()
            media_type = f"image/{image_format}" if image_format in ['jpeg', 'png', 'gif', 'webp'] else "image/jpeg"
            
            prompt = f"""Analyze this image file (filename: "{filename}") and extract structured metadata.

Available categories (choose the MOST appropriate one):
{json.dumps(self.CATEGORIES, indent=2)}

Provide your analysis in JSON format:
{{
  "category": "one of the categories from the list",
  "subcategory": "more specific classification",
  "summary": "describe what's in the image and its likely purpose",
  "tags": ["relevant", "keywords", "describing", "content"],
  "entities": {{
    "people": ["if you can identify any text with names"],
    "organizations": ["any visible company names/logos"],
    "locations": ["any locations visible or mentioned"],
    "dates": ["any dates visible in the image"]
  }},
  "key_info": {{
    "image_type": "describe type (screenshot, receipt, document photo, diagram, etc.)",
    "text_detected": "any important text visible in the image",
    "contains_sensitive_info": true/false
  }},
  "confidence_score": 0.0 to 1.0
}}

Respond ONLY with valid JSON."""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            response_text = response.content[0].text.strip()
            
            # Clean markdown if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            
            metadata = json.loads(response_text)
            return self._validate_metadata(metadata)
            
        except Exception as e:
            print(f"Image analysis error: {str(e)}")
            return self._get_default_metadata(f"Image analysis failed: {str(e)}")
    
    def _validate_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and ensure all required fields are present"""
        validated = {
            "category": metadata.get("category", "Other"),
            "subcategory": metadata.get("subcategory", ""),
            "summary": metadata.get("summary", "")[:500],  # Limit summary length
            "tags": metadata.get("tags", [])[:10],  # Max 10 tags
            "entities": metadata.get("entities", {}),
            "key_info": metadata.get("key_info", {}),
            "confidence_score": float(metadata.get("confidence_score", 0.5))
        }
        
        # Ensure category is valid
        if validated["category"] not in self.CATEGORIES:
            validated["category"] = "Other"
        
        return validated
    
    def _get_default_metadata(self, reason: str = "") -> Dict[str, Any]:
        """Return default metadata when processing fails"""
        return {
            "category": "Other",
            "subcategory": "",
            "summary": reason or "File processed without AI analysis",
            "tags": [],
            "entities": {},
            "key_info": {},
            "confidence_score": 0.0
        }
    
    def semantic_search(self, query: str, user_files_metadata: List[Dict]) -> List[Dict]:
        """
        Perform semantic search using embeddings (MUCH faster than Claude API)
        Returns ranked list of files with relevance scores
        """
        if not user_files_metadata or not self.embedding_model:
            return []
        
        try:
            # Compute query embedding
            query_embedding = self.compute_embedding(query)
            print(query_embedding, 'query_embedding')
            if not query_embedding:
                return []
            
            # Filter files that have embeddings
            files_with_embeddings = [
                f for f in user_files_metadata 
                if f.get('embedding') is not None
            ]
            
            if not files_with_embeddings:
                return []
            
            # Compute similarities
            file_embeddings = np.array([f['embedding'] for f in files_with_embeddings])
            similarities = cosine_similarity([query_embedding], file_embeddings)[0]
            
            # Create results with scores
            results = []
            for i, file_data in enumerate(files_with_embeddings):
                score = float(similarities[i])
                if score >= 0.3:  # Relevance threshold
                    results.append({
                        'file_id': file_data['file_id'],
                        'relevance_score': score,
                        'reason': f"Semantic similarity: {score:.2f}"
                    })
            
            # Sort by relevance and return top 10
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            return results[:10]
            
        except Exception as e:
            print(f"Semantic search error: {str(e)}")
            return []