"""
📰 RSS Service - парсинг трендів з дизайнерських сайтів
Джерела для ідей контенту про плитку, ремонт, дизайн ванних кімнат.
"""
import feedparser
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import re
import os
import json

# RSS-ленти з дизайну та ремонту
RSS_FEEDS = {
    'dezeen': {
        'url': 'https://www.dezeen.com/interiors/feed/',
        'name': 'Dezeen Interiors',
        'category': 'design',
        'language': 'en'
    },
    'archdaily': {
        'url': 'https://www.archdaily.com/feed',
        'name': 'ArchDaily',
        'category': 'architecture',
        'language': 'en'
    },
    'houzz': {
        'url': 'https://www.houzz.com/rss/stories',
        'name': 'Houzz Stories',
        'category': 'home_design',
        'language': 'en'
    },
    'dwell': {
        'url': 'https://www.dwell.com/feed',
        'name': 'Dwell',
        'category': 'modern_design',
        'language': 'en'
    },
    'designboom': {
        'url': 'https://www.designboom.com/feed/',
        'name': 'Designboom',
        'category': 'design',
        'language': 'en'
    },
    'schoener_wohnen': {
        'url': 'https://www.schoener-wohnen.de/rss/news.xml',
        'name': 'Schöner Wohnen',
        'category': 'home_design',
        'language': 'de'
    }
}


def _normalize_feeds(parsed: Any) -> Dict[str, Dict]:
    """Normalize feeds input into the internal dict format."""
    # Формат 1: {"key": {"url": "...", "name": "...", ...}, ...}
    if isinstance(parsed, dict):
        feeds: Dict[str, Dict] = {}
        for key, value in parsed.items():
            if isinstance(value, str):
                url = value.strip()
                if not url:
                    continue
                feeds[str(key)] = {
                    'url': url,
                    'name': str(key),
                    'category': 'custom',
                    'language': 'en'
                }
            elif isinstance(value, dict) and value.get('url'):
                url = str(value.get('url') or '').strip()
                if not url:
                    continue
                feeds[str(key)] = {
                    'url': url,
                    'name': value.get('name', str(key)),
                    'category': value.get('category', 'custom'),
                    'language': value.get('language', 'en')
                }
        return feeds

    # Формат 2: ["https://example.com/feed.xml", ...]
    if isinstance(parsed, list):
        feeds = {}
        i = 0
        for raw_url in parsed:
            if not isinstance(raw_url, str):
                continue
            url = raw_url.strip()
            if not url:
                continue
            i += 1
            feeds[f'feed_{i}'] = {
                'url': url,
                'name': f'Feed {i}',
                'category': 'custom',
                'language': 'en'
            }
        return feeds

    return {}


def get_rss_feeds_config(user_id: Optional[str] = None) -> Dict[str, Dict]:
    """Отримати конфіг RSS-лент: per-user (DB) → env (RSS_FEEDS_JSON) → дефолт."""
    # 1) Per-user DB override
    if user_id:
        try:
            from models import RssFeedSettings
            row = RssFeedSettings.query.filter_by(user_id=user_id).first()
            if row and row.feeds:
                feeds = _normalize_feeds(row.feeds)
                if feeds:
                    return feeds
        except Exception:
            # If DB/app context isn't available, fall back to env/default.
            pass

    # 2) Global env override
    raw = os.environ.get('RSS_FEEDS_JSON', '').strip()
    if raw:
        try:
            parsed = json.loads(raw)
            feeds = _normalize_feeds(parsed)
            if feeds:
                return feeds
        except Exception:
            pass

    # 3) Hardcoded default
    return RSS_FEEDS

# Ключові слова для фільтрації релевантного контенту
RELEVANT_KEYWORDS = [
    # Англійська
    'tile', 'tiles', 'bathroom', 'bath', 'shower', 'renovation', 
    'interior', 'design', 'ceramic', 'porcelain', 'marble',
    'floor', 'flooring', 'wall', 'kitchen', 'sink', 'faucet',
    'modern', 'minimalist', 'luxury', 'trend', 'color',
    
    # Німецька
    'fliesen', 'bad', 'badezimmer', 'dusche', 'renovierung',
    'innendesign', 'keramik', 'marmor', 'boden', 'wand',
    'küche', 'waschbecken', 'modern', 'luxus', 'trend', 'farbe',
    
    # Загальні
    '2024', '2025', 'trend', 'new', 'neu', 'design'
]


def fetch_rss_feed(feed_key: str, feeds: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """
    Отримати статті з конкретної RSS-ленти
    
    Args:
        feed_key: Ключ ленти з RSS_FEEDS
        
    Returns:
        List[Dict] зі статтями
    """
    feeds = feeds or get_rss_feeds_config()
    if feed_key not in feeds:
        return []
    
    feed_config = feeds[feed_key]
    
    try:
        feed = feedparser.parse(feed_config['url'])
        
        articles = []
        for entry in feed.entries[:20]:  # Останні 20 статей
            # Спроба витягнути зображення (якщо RSS його надає)
            image_url = None
            try:
                if hasattr(entry, 'media_content') and entry.media_content:
                    mc = entry.media_content[0]
                    if isinstance(mc, dict):
                        image_url = mc.get('url')
                if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    mt = entry.media_thumbnail[0]
                    if isinstance(mt, dict):
                        image_url = mt.get('url')
            except Exception:
                image_url = None

            # Дата публікації
            published = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])
            
            # Зміст
            content_html = ''
            if hasattr(entry, 'summary') and entry.summary:
                content_html = entry.summary
            elif hasattr(entry, 'content') and entry.content:
                content_html = entry.content[0].value if entry.content else ''

            # Витягуємо перше зображення з HTML, якщо media_* не було
            if not image_url and content_html:
                m = re.search(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', content_html, flags=re.IGNORECASE)
                if m:
                    image_url = m.group(1)
            
            # Очищаємо HTML
            content = re.sub(r'<[^>]+>', '', content_html or '')
            
            articles.append({
                'title': entry.get('title', 'No title'),
                'link': entry.get('link', ''),
                'content': content[:500],  # Обмежуємо
                'published': published,
                'source': feed_config['name'],
                'category': feed_config['category'],
                'language': feed_config['language'],
                'image_url': image_url
            })
        
        return articles
        
    except Exception as e:
        print(f"❌ Помилка парсингу {feed_key}: {e}")
        return []


def fetch_all_feeds(feeds: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """
    Отримати статті з усіх RSS-лент
    
    Returns:
        List[Dict] всіх статей, відсортованих за датою
    """
    all_articles = []

    feeds = feeds or get_rss_feeds_config()
    
    for feed_key in feeds:
        print(f"📡 Завантаження {feeds[feed_key]['name']}...")
        articles = fetch_rss_feed(feed_key, feeds=feeds)
        all_articles.extend(articles)
        print(f"   ✅ {len(articles)} статей")
    
    # Сортуємо за датою
    all_articles.sort(key=lambda x: x.get('published') or datetime.min, reverse=True)
    
    return all_articles


def filter_relevant_articles(articles: List[Dict], 
                             keywords: List[str] = None) -> List[Dict]:
    """
    Фільтрація релевантних статей за ключовими словами
    
    Args:
        articles: Список статей
        keywords: Ключові слова для фільтрації (за замовчуванням RELEVANT_KEYWORDS)
        
    Returns:
        List[Dict] відфільтрованих статей
    """
    if keywords is None:
        keywords = RELEVANT_KEYWORDS
    
    keywords_lower = [k.lower() for k in keywords]
    
    relevant = []
    for article in articles:
        text = f"{article['title']} {article['content']}".lower()
        
        # Перевіряємо чи містить будь-яке ключове слово
        matches = [kw for kw in keywords_lower if kw in text]
        
        if matches:
            article['matched_keywords'] = matches
            article['relevance_score'] = len(matches)
            relevant.append(article)
    
    # Сортуємо за релевантністю
    relevant.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    return relevant


def get_trending_topics(days: int = 7, max_topics: int = 10, user_id: Optional[str] = None) -> List[Dict]:
    """
    Отримати актуальні тренди за останні N днів
    
    Args:
        days: Кількість днів для аналізу
        max_topics: Максимум топіків
        
    Returns:
        List[Dict] трендових тем
    """
    feeds = get_rss_feeds_config(user_id=user_id)
    all_articles = fetch_all_feeds(feeds=feeds)
    
    # Фільтруємо за датою
    cutoff = datetime.now() - timedelta(days=days)
    recent = [a for a in all_articles if a.get('published') and a['published'] > cutoff]
    
    # Фільтруємо релевантні
    relevant = filter_relevant_articles(recent)
    
    return relevant[:max_topics]


def generate_content_ideas_from_trends(trends: List[Dict]) -> List[Dict]:
    """
    Генерація ідей для контенту на основі трендів
    (Базова версія без AI)
    
    Args:
        trends: Список трендів
        
    Returns:
        List[Dict] ідей для контенту
    """
    ideas = []
    
    post_templates = [
        "🔥 Тренд: {title}\n\nЯк ми застосовуємо це у наших проектах ванних кімнат у Франкфурті!",
        "💡 Натхнення: {title}\n\nЗверніться до нас для втілення сучасних ідей у вашій ванній!",
        "📊 Новинка в дизайні: {title}\n\nМи слідкуємо за трендами щоб ваша ванна була стильною!",
        "🏠 Ідея для вашого дому: {title}\n\nБезкоштовна консультація по дизайну ванної!"
    ]
    
    for i, trend in enumerate(trends[:5]):
        template = post_templates[i % len(post_templates)]
        
        ideas.append({
            'source_trend': trend['title'],
            'source_link': trend['link'],
            'post_idea': template.format(title=trend['title'][:100]),
            'hashtags': [
                '#fliesen', '#badsanierung', '#frankfurt',
                '#bathroom', '#design', '#trend', '#renovierung',
                '#interiordesign', '#home', '#inspiration'
            ],
            'content_type': 'trend_based',
            'keywords': trend.get('matched_keywords', [])
        })
    
    return ideas


# Тест
if __name__ == '__main__':
    print("🧪 Тест RSS Service...")
    
    print("\n📡 Завантаження трендів...")
    trends = get_trending_topics(days=14, max_topics=5)
    
    print(f"\n📊 Знайдено {len(trends)} релевантних статей:")
    for i, trend in enumerate(trends[:5], 1):
        print(f"\n{i}. {trend['title'][:80]}...")
        print(f"   📍 Джерело: {trend['source']}")
        print(f"   🏷️ Ключові слова: {', '.join(trend.get('matched_keywords', [])[:5])}")
    
    print("\n💡 Генерація ідей для контенту...")
    ideas = generate_content_ideas_from_trends(trends)
    
    for idea in ideas[:3]:
        print(f"\n📝 {idea['post_idea'][:150]}...")
