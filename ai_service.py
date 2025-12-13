"""
🤖 AI Service - інтеграція з OpenAI для OSINTGRAM
Функціонал:
- Аналіз профілів Instagram
- Генерація персоналізованих повідомлень
- Генерація контенту для публікацій
- Обробка трендів з RSS
"""
import os
import json
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

# OpenAI API
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# Контекст бізнесу (для персоналізації)
BUSINESS_CONTEXT = """
Ми - компанія з укладання плитки та ремонту ванних кімнат у регіоні Франкфурт (Німеччина).
Наші послуги:
- Укладання плитки (Fliesen legen)
- Ремонт ванних кімнат (Badsanierung)
- Сантехнічні роботи
- Дизайн інтер'єру ванних кімнат

Наша цільова аудиторія:
- Власники будинків/квартир у Франкфурті та околицях (100 км)
- Люди, зацікавлені в ремонті
- Підписники конкурентів (дизайн інтер'єру, магазини плитки, ремонтні компанії)

Тон комунікації: професійний, дружній, на "ви", німецькою або англійською.
"""


def get_openai_client():
    """Отримати клієнт OpenAI"""
    if not OPENAI_API_KEY:
        return None
    
    try:
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("⚠️ openai package not installed. Run: pip install openai")
        return None


def analyze_profile(username: str, bio: str, followers_count: int = 0, 
                   posts_count: int = 0, is_business: bool = False) -> Dict:
    """
    🧠 Аналіз профілю через AI
    
    Визначає:
    - Тип профілю: потенційний_клієнт, конкурент, постачальник, інфлюенсер, нерелевантний
    - Quality score: 0-100
    - Рекомендації щодо контакту
    
    Args:
        username: Instagram username
        bio: Біографія профілю
        followers_count: Кількість підписників
        posts_count: Кількість постів
        is_business: Чи бізнес-акаунт
        
    Returns:
        Dict з результатами аналізу
    """
    client = get_openai_client()
    
    if not client:
        # Fallback без AI
        return {
            'profile_type': 'потенційний_клієнт',
            'quality_score': 50,
            'is_target_audience': True,
            'reasoning': 'AI недоступний - базова оцінка',
            'contact_recommendation': 'Можна контактувати',
            'suggested_message_tone': 'дружній'
        }
    
    prompt = f"""Проаналізуй Instagram профіль для компанії з укладання плитки у Франкфурті.

ПРОФІЛЬ:
- Username: @{username}
- Біографія: {bio or 'Немає'}
- Підписників: {followers_count}
- Постів: {posts_count}
- Бізнес-акаунт: {'Так' if is_business else 'Ні'}

КОНТЕКСТ БІЗНЕСУ:
{BUSINESS_CONTEXT}

ЗАВДАННЯ:
Визнач тип профілю та оціни якість як потенційного клієнта.

Відповідь у JSON форматі:
{{
    "profile_type": "потенційний_клієнт|конкурент|постачальник|інфлюенсер|нерелевантний",
    "quality_score": 0-100,
    "is_target_audience": true/false,
    "reasoning": "коротке пояснення",
    "contact_recommendation": "рекомендація щодо контакту",
    "suggested_message_tone": "дружній|діловий|casual",
    "interests_detected": ["список", "інтересів"]
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти експерт з аналізу соціальних мереж для B2C маркетингу. Відповідай тільки валідним JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        result_text = response.choices[0].message.content.strip()
        # Очищаємо від markdown
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        return json.loads(result_text)
        
    except Exception as e:
        print(f"❌ AI аналіз помилка: {e}")
        return {
            'profile_type': 'потенційний_клієнт',
            'quality_score': 50,
            'is_target_audience': True,
            'reasoning': f'AI помилка: {str(e)}',
            'contact_recommendation': 'Можна контактувати',
            'suggested_message_tone': 'дружній'
        }


def generate_personalized_message(recipient_username: str, recipient_bio: str,
                                  recipient_name: str = None,
                                  message_goal: str = "знайомство") -> Dict:
    """
    ✍️ Генерація персоналізованого повідомлення
    
    Args:
        recipient_username: Username отримувача
        recipient_bio: Біографія отримувача
        recipient_name: Ім'я отримувача
        message_goal: Мета повідомлення (знайомство, пропозиція, знижка)
        
    Returns:
        Dict з варіантами повідомлень
    """
    client = get_openai_client()
    
    if not client:
        # Fallback шаблон
        name = recipient_name or recipient_username
        return {
            'messages': [
                f"Привіт, {name}! 👋 Ми займаємось укладанням плитки та ремонтом ванних у Франкфурті. Цікавить безкоштовна консультація?",
            ],
            'recommended': 0,
            'ai_generated': False
        }
    
    goal_prompts = {
        'знайомство': 'Перше знайомство, м\'який підхід, без нав\'язування',
        'пропозиція': 'Конкретна пропозиція послуг',
        'знижка': 'Спеціальна пропозиція/знижка для нових клієнтів',
        'follow_up': 'Нагадування/повторний контакт'
    }
    
    prompt = f"""Створи 3 варіанти персоналізованого повідомлення для Instagram Direct.

ОТРИМУВАЧ:
- Username: @{recipient_username}
- Ім'я: {recipient_name or 'Невідоме'}
- Біографія: {recipient_bio or 'Немає'}

МЕТА: {goal_prompts.get(message_goal, message_goal)}

ВІДПРАВНИК:
{BUSINESS_CONTEXT}

ВИМОГИ:
1. Повідомлення 50-150 слів
2. Персоналізація на основі біографії
3. Природний тон, не спам
4. Можна використовувати емодзі (1-3)
5. Німецька або українська мова
6. Call-to-action в кінці

Відповідь у JSON:
{{
    "messages": ["варіант 1", "варіант 2", "варіант 3"],
    "recommended": 0,
    "personalization_notes": "що персоналізовано"
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти копірайтер для Instagram маркетингу. Пишеш природні, персоналізовані повідомлення."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        result = json.loads(result_text)
        result['ai_generated'] = True
        return result
        
    except Exception as e:
        print(f"❌ Генерація повідомлення помилка: {e}")
        name = recipient_name or recipient_username
        return {
            'messages': [f"Привіт, {name}! Ми займаємось ремонтом ванних у Франкфурті. Зацікавлені?"],
            'recommended': 0,
            'ai_generated': False,
            'error': str(e)
        }


def generate_post_content(topic: str, post_type: str = "informative",
                         include_hashtags: bool = True) -> Dict:
    """
    📝 Генерація контенту для публікації в Instagram
    
    Args:
        topic: Тема поста (напр. "тренди плитки 2025", "поради ремонту ванної")
        post_type: Тип поста (informative, promotional, behind_scenes, tips)
        include_hashtags: Чи додавати хештеги
        
    Returns:
        Dict з контентом поста
    """
    client = get_openai_client()
    
    if not client:
        return {
            'caption': f"🔨 {topic}\n\nЗвертайтесь до нас за якісним ремонтом! 📞",
            'hashtags': ['#fliesen', '#badsanierung', '#frankfurt'],
            'ai_generated': False
        }
    
    type_prompts = {
        'informative': 'Інформативний пост з корисними порадами',
        'promotional': 'Рекламний пост з call-to-action',
        'behind_scenes': 'За лаштунками роботи, показати процес',
        'tips': 'Корисні поради для власників будинків',
        'before_after': 'До/Після проекту ремонту',
        'trend': 'Тренди та новинки в дизайні'
    }
    
    prompt = f"""Створи контент для Instagram поста.

ТЕМА: {topic}
ТИП: {type_prompts.get(post_type, post_type)}

БІЗНЕС:
{BUSINESS_CONTEXT}

ВИМОГИ:
1. Caption 100-200 слів
2. Привабливий перший рядок (hook)
3. Emoji для візуального оформлення
4. Call-to-action в кінці
5. Німецька мова (основна) з англійськими термінами
6. 15-20 релевантних хештегів

Відповідь у JSON:
{{
    "hook": "перший рядок для привернення уваги",
    "caption": "повний текст поста",
    "hashtags": ["список", "хештегів"],
    "best_time_to_post": "рекомендований час",
    "content_ideas": ["ідея для фото 1", "ідея для фото 2"]
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти SMM спеціаліст для Instagram. Створюєш вірусний контент для бізнес-акаунтів."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=1000
        )
        
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        result = json.loads(result_text)
        result['ai_generated'] = True
        return result
        
    except Exception as e:
        print(f"❌ Генерація поста помилка: {e}")
        return {
            'caption': f"🔨 {topic}\n\nЗвертайтесь до нас! 📞",
            'hashtags': ['#fliesen', '#frankfurt', '#renovierung'],
            'ai_generated': False,
            'error': str(e)
        }


def summarize_trend(trend_title: str, trend_content: str) -> Dict:
    """
    📰 Саммарі тренду з RSS для ідей контенту
    
    Args:
        trend_title: Заголовок статті/тренду
        trend_content: Текст статті
        
    Returns:
        Dict з саммарі та ідеями
    """
    client = get_openai_client()
    
    if not client:
        return {
            'summary': trend_title,
            'post_ideas': [f"Пост про: {trend_title}"],
            'ai_generated': False
        }
    
    prompt = f"""Проаналізуй тренд з дизайну/ремонту та створи ідеї для Instagram контенту.

ТРЕНД:
Заголовок: {trend_title}
Зміст: {trend_content[:2000]}

БІЗНЕС: Укладання плитки та ремонт ванних у Франкфурті

ЗАВДАННЯ:
1. Коротке саммарі тренду (2-3 речення)
2. Як це стосується нашого бізнесу
3. 3 ідеї для Instagram постів на основі цього тренду

JSON відповідь:
{{
    "summary": "коротке саммарі",
    "relevance": "як стосується нашого бізнесу",
    "post_ideas": [
        {{"title": "назва поста", "description": "опис", "type": "тип поста"}},
        ...
    ]
}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти контент-стратег для Instagram в ніші ремонту та дизайну."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6,
            max_tokens=600
        )
        
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith('```'):
            result_text = result_text.split('```')[1]
            if result_text.startswith('json'):
                result_text = result_text[4:]
        
        result = json.loads(result_text)
        result['ai_generated'] = True
        return result
        
    except Exception as e:
        return {
            'summary': trend_title,
            'post_ideas': [],
            'ai_generated': False,
            'error': str(e)
        }


def batch_analyze_profiles(profiles: List[Dict], max_profiles: int = 50) -> List[Dict]:
    """
    🔄 Пакетний аналіз профілів
    
    Args:
        profiles: Список профілів [{username, bio, followers_count, ...}]
        max_profiles: Максимум профілів для аналізу
        
    Returns:
        List[Dict] з результатами аналізу
    """
    results = []
    
    for i, profile in enumerate(profiles[:max_profiles]):
        print(f"🔍 Аналіз профілю {i+1}/{min(len(profiles), max_profiles)}: @{profile.get('username', 'N/A')}")
        
        analysis = analyze_profile(
            username=profile.get('username', ''),
            bio=profile.get('biography', '') or profile.get('bio', ''),
            followers_count=profile.get('followers_count', 0),
            posts_count=profile.get('posts_count', 0),
            is_business=profile.get('is_business', False)
        )
        
        results.append({
            **profile,
            'ai_analysis': analysis
        })
    
    return results


# Тест
if __name__ == '__main__':
    print("🧪 Тест AI Service...")
    
    if OPENAI_API_KEY:
        print(f"✅ OpenAI API Key знайдено: {OPENAI_API_KEY[:10]}...")
        
        # Тест аналізу профілю
        result = analyze_profile(
            username="test_user",
            bio="Люблю дизайн інтер'єру 🏠 Frankfurt | Шукаю ідеї для ремонту ванної",
            followers_count=500
        )
        print(f"\n📊 Результат аналізу: {json.dumps(result, indent=2, ensure_ascii=False)}")
    else:
        print("⚠️ OPENAI_API_KEY не знайдено в .env")
        print("Додайте: OPENAI_API_KEY=sk-...")
