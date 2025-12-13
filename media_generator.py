"""
🎨 Media Generation Service
Інтеграція з AI для генерації зображень та відео:
- OpenAI DALL-E 3 (зображення)
- Runway ML (відео/анімація) 
- Stability AI (зображення)
- Leonardo AI (зображення)
"""
import os
import requests
import json
from typing import Dict, Optional
from datetime import datetime
import uuid
from dotenv import load_dotenv

load_dotenv()

# API ключі з .env
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
RUNWAY_API_KEY = os.environ.get('RUNWAY_API_KEY')
STABILITY_API_KEY = os.environ.get('STABILITY_API_KEY')
LEONARDO_API_KEY = os.environ.get('LEONARDO_API_KEY')

# Папка для збереження медіа
MEDIA_DIR = os.path.join(os.path.dirname(__file__), 'uploads', 'generated')
os.makedirs(MEDIA_DIR, exist_ok=True)


class MediaGenerator:
    """Генератор медіа контенту через різні AI API"""
    
    def __init__(self):
        self.providers = {
            'dalle': bool(OPENAI_API_KEY),
            'runway': bool(RUNWAY_API_KEY),
            'stability': bool(STABILITY_API_KEY),
            'leonardo': bool(LEONARDO_API_KEY)
        }
    
    def get_available_providers(self) -> Dict[str, bool]:
        """Отримати список доступних провайдерів"""
        return self.providers
    
    def generate_image_dalle(self, prompt: str, size: str = "1024x1024", 
                            style: str = "vivid") -> Dict:
        """
        🖼️ Генерація зображення через DALL-E 3
        
        Args:
            prompt: Опис зображення
            size: Розмір (1024x1024, 1792x1024, 1024x1792)
            style: Стиль (vivid, natural)
            
        Returns:
            Dict з URL зображення або помилкою
        """
        if not OPENAI_API_KEY:
            return {'success': False, 'error': 'OPENAI_API_KEY не налаштовано'}
        
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            
            # Додаємо контекст для кращих результатів
            enhanced_prompt = f"""Professional interior design photo for Instagram.
{prompt}
Style: modern, minimalist, high-end photography, perfect lighting, 4K quality.
Focus: bathroom renovation, tiles, Fliesen, Badsanierung."""
            
            response = client.images.generate(
                model="dall-e-3",
                prompt=enhanced_prompt,
                size=size,
                style=style,
                quality="hd",
                n=1
            )
            
            image_url = response.data[0].url
            revised_prompt = response.data[0].revised_prompt
            
            # Завантажуємо і зберігаємо локально
            local_path = self._download_image(image_url, 'dalle')
            
            return {
                'success': True,
                'provider': 'dalle',
                'url': image_url,
                'local_path': local_path,
                'revised_prompt': revised_prompt,
                'size': size
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'provider': 'dalle'}
    
    def generate_video_runway(self, prompt: str, image_url: str = None,
                             duration: int = 4) -> Dict:
        """
        🎬 Генерація відео через Runway ML (Gen-3)
        
        Args:
            prompt: Опис руху/анімації
            image_url: URL зображення для анімації (опціонально)
            duration: Тривалість в секундах (4, 8, 16)
            
        Returns:
            Dict з URL відео або помилкою
        """
        if not RUNWAY_API_KEY:
            return {'success': False, 'error': 'RUNWAY_API_KEY не налаштовано'}
        
        try:
            headers = {
                'Authorization': f'Bearer {RUNWAY_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            # Runway Gen-3 Alpha API
            payload = {
                'prompt': prompt,
                'duration': duration,
                'ratio': '16:9'
            }
            
            if image_url:
                payload['image_url'] = image_url
                payload['mode'] = 'image_to_video'
            else:
                payload['mode'] = 'text_to_video'
            
            # Створюємо задачу
            response = requests.post(
                'https://api.runwayml.com/v1/generations',
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'provider': 'runway',
                    'task_id': result.get('id'),
                    'status': 'processing',
                    'message': 'Відео генерується... Перевірте статус через кілька хвилин.'
                }
            else:
                return {
                    'success': False,
                    'error': f"Runway API error: {response.status_code} - {response.text}",
                    'provider': 'runway'
                }
                
        except Exception as e:
            return {'success': False, 'error': str(e), 'provider': 'runway'}
    
    def check_runway_status(self, task_id: str) -> Dict:
        """Перевірити статус генерації Runway"""
        if not RUNWAY_API_KEY:
            return {'success': False, 'error': 'RUNWAY_API_KEY не налаштовано'}
        
        try:
            headers = {'Authorization': f'Bearer {RUNWAY_API_KEY}'}
            
            response = requests.get(
                f'https://api.runwayml.com/v1/generations/{task_id}',
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                status = result.get('status')
                
                if status == 'completed':
                    video_url = result.get('output', {}).get('video_url')
                    local_path = self._download_video(video_url, 'runway')
                    return {
                        'success': True,
                        'status': 'completed',
                        'url': video_url,
                        'local_path': local_path
                    }
                elif status == 'failed':
                    return {
                        'success': False,
                        'status': 'failed',
                        'error': result.get('error')
                    }
                else:
                    return {
                        'success': True,
                        'status': status,
                        'progress': result.get('progress', 0)
                    }
            else:
                return {'success': False, 'error': f"API error: {response.status_code}"}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def generate_image_stability(self, prompt: str, 
                                 style_preset: str = "photographic") -> Dict:
        """
        🖼️ Генерація через Stability AI (SDXL)
        
        Args:
            prompt: Опис зображення
            style_preset: Стиль (photographic, digital-art, cinematic, etc.)
        """
        if not STABILITY_API_KEY:
            return {'success': False, 'error': 'STABILITY_API_KEY не налаштовано'}
        
        try:
            headers = {
                'Authorization': f'Bearer {STABILITY_API_KEY}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            payload = {
                'text_prompts': [
                    {'text': prompt, 'weight': 1},
                    {'text': 'blurry, bad quality, distorted', 'weight': -1}
                ],
                'cfg_scale': 7,
                'height': 1024,
                'width': 1024,
                'samples': 1,
                'steps': 30,
                'style_preset': style_preset
            }
            
            response = requests.post(
                'https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image',
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                # Base64 зображення
                image_b64 = result['artifacts'][0]['base64']
                local_path = self._save_base64_image(image_b64, 'stability')
                
                return {
                    'success': True,
                    'provider': 'stability',
                    'local_path': local_path
                }
            else:
                return {'success': False, 'error': f"API error: {response.status_code}"}
                
        except Exception as e:
            return {'success': False, 'error': str(e), 'provider': 'stability'}
    
    def create_instagram_content(self, topic: str, style: str = "modern") -> Dict:
        """
        📸 Створити готовий контент для Instagram
        
        Args:
            topic: Тема контенту
            style: Стиль (modern, luxury, minimalist, rustic)
            
        Returns:
            Dict з зображенням, caption та хештегами
        """
        # Генеруємо промпт для зображення
        style_prompts = {
            'modern': 'modern minimalist bathroom, clean lines, white tiles, chrome fixtures',
            'luxury': 'luxury spa bathroom, marble tiles, gold accents, ambient lighting',
            'minimalist': 'scandinavian bathroom, wooden accents, neutral tones, plants',
            'rustic': 'mediterranean bathroom, terracotta tiles, natural stone, warm lighting',
            'industrial': 'industrial loft bathroom, concrete, black fixtures, exposed pipes'
        }
        
        base_prompt = style_prompts.get(style, style_prompts['modern'])
        full_prompt = f"{topic}. {base_prompt}. Professional interior photography for Instagram, 4K, perfect lighting."
        
        # Генеруємо зображення
        image_result = self.generate_image_dalle(full_prompt)
        
        if not image_result['success']:
            return image_result
        
        # Генеруємо caption через AI
        from ai_service import generate_post_content
        content = generate_post_content(topic=topic, post_type='trend')
        
        return {
            'success': True,
            'image': image_result,
            'caption': content.get('caption', ''),
            'hashtags': content.get('hashtags', []),
            'hook': content.get('hook', ''),
            'topic': topic,
            'style': style
        }
    
    def _download_image(self, url: str, provider: str) -> str:
        """Завантажити зображення локально"""
        try:
            response = requests.get(url, timeout=30)
            filename = f"{provider}_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(MEDIA_DIR, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return filepath
        except:
            return None
    
    def _download_video(self, url: str, provider: str) -> str:
        """Завантажити відео локально"""
        try:
            response = requests.get(url, timeout=120)
            filename = f"{provider}_{uuid.uuid4().hex[:8]}.mp4"
            filepath = os.path.join(MEDIA_DIR, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return filepath
        except:
            return None
    
    def _save_base64_image(self, b64_data: str, provider: str) -> str:
        """Зберегти base64 зображення"""
        import base64
        try:
            filename = f"{provider}_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(MEDIA_DIR, filename)
            
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(b64_data))
            
            return filepath
        except:
            return None


# Глобальний екземпляр
media_generator = MediaGenerator()


# Тест
if __name__ == '__main__':
    print("🎨 Media Generator Status:")
    print(f"   Providers: {media_generator.get_available_providers()}")
    
    if OPENAI_API_KEY:
        print("\n🖼️ Тест DALL-E...")
        result = media_generator.generate_image_dalle(
            "Modern bathroom with large format grey tiles, walk-in shower, minimalist design"
        )
        print(f"   Result: {result}")
