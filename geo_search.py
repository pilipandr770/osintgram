"""
Модуль автоматичного пошуку схожих сторінок та геолокації.
Для пошуку цільової аудиторії в Instagram.
"""
from typing import List, Dict, Optional, Set
import re

# ============ ГЕОЛОКАЦІЯ: Міста в радіусі 100 км від Франкфурта ============

FRANKFURT_REGION_CITIES = [
    # Головні міста
    "frankfurt", "frankfurt am main", "ffm",
    "offenbach", "offenbach am main",
    "darmstadt",
    "mainz",
    "wiesbaden",
    "hanau",
    "aschaffenburg",
    "gießen", "giessen",
    "fulda",
    "marburg",
    "bad homburg",
    "friedberg",
    "bad vilbel",
    "oberursel",
    "kronberg",
    "königstein", "koenigstein",
    "bad soden",
    "eschborn",
    "kelsterbach",
    "rüsselsheim", "ruesselsheim",
    "groß-gerau", "gross-gerau",
    "bensheim",
    "viernheim",
    "lampertheim",
    "heppenheim",
    "weinheim",
    "heidelberg",  # трохи далі, але важливе місто
    "mannheim",    # трохи далі, але важливе місто
    "worms",
    "bingen",
    "ingelheim",
    "bad kreuznach",
    "limburg",
    "koblenz",     # на межі 100 км
    
    # Райони/округи
    "rhein-main", "rhein main",
    "main-taunus", "main taunus",
    "hochtaunus",
    "wetterau",
    "bergstraße", "bergstrasse",
]

# Німецькі поштові індекси Франкфуртського регіону (60xxx - 65xxx)
FRANKFURT_POSTAL_CODES = [f"{i}" for i in range(60000, 66000)]


# ============ КЛЮЧОВІ СЛОВА ДЛЯ РЕМОНТУ/КАФЕЛЮ ============

# Німецькою
KEYWORDS_DE = [
    # Кафель/плитка
    "fliesen", "fliesenleger", "fliesenarbeiten", "fliesendesign",
    "bodenfliesen", "wandfliesen", "mosaikfliesen", "natursteinfliesen",
    
    # Ванна кімната
    "badezimmer", "bad renovierung", "badsanierung", "badumbau",
    "baddesign", "badgestaltung", "traumbad",
    
    # Ремонт загальний
    "renovierung", "sanierung", "modernisierung", "umbau",
    "raumgestaltung", "innenausbau",
    
    # Кухня
    "küche", "kueche", "küchenrenovierung", "kuechenrenovierung",
    
    # Будівництво
    "handwerker", "bauunternehmen", "baufirma",
    "trockenbau", "malerarbeiten", "bodenbelag",
    
    # Дизайн інтер'єру
    "interior", "interiordesign", "raumdesign", "wohndesign",
    "einrichtung", "homedesign",
]

# Англійською (популярні теги)
KEYWORDS_EN = [
    "tiles", "tiling", "tile design", "tile installation",
    "bathroom", "bathroom renovation", "bathroom design",
    "renovation", "home renovation", "interior design",
    "kitchen renovation", "flooring",
]

# Хештеги для пошуку
HASHTAGS_SEARCH = [
    # Німецькі - кафель
    "fliesen", "fliesenleger", "fliesendesign", "fliesenliebe",
    "fliesenarbeiten", "fliesenkunst",
    
    # Ванна
    "badsanierung", "badezimmerdesign", "badezimmer", "traumbad",
    "badezimmerideen", "badrenovierung",
    
    # Ремонт
    "renovierung", "sanierung", "handwerk", "handwerker",
    "innenausbau", "modernisierung",
    
    # Регіон
    "frankfurtammain", "frankfurt", "rheinmain",
    "offenbach", "darmstadt", "mainz", "wiesbaden",
    
    # Комбіновані
    "fliesenfrankfurt", "badfrankfurt", "renovierungfrankfurt",
]


def check_location_match(bio: str, location: str = None) -> Dict:
    """
    Перевірити, чи профіль знаходиться в регіоні Франкфурта.
    
    Args:
        bio: Біографія профілю
        location: Локація з профілю (якщо є)
        
    Returns:
        Dict: {matched: bool, city: str or None, confidence: str}
    """
    text = f"{bio or ''} {location or ''}".lower()
    
    # Перевіряємо поштові індекси
    postal_match = re.search(r'\b(6[0-5]\d{3})\b', text)
    if postal_match:
        return {
            "matched": True,
            "city": f"PLZ {postal_match.group(1)}",
            "confidence": "high"
        }
    
    # Перевіряємо міста
    for city in FRANKFURT_REGION_CITIES:
        if city in text:
            return {
                "matched": True,
                "city": city.title(),
                "confidence": "high" if city in ["frankfurt", "offenbach", "darmstadt", "mainz", "wiesbaden"] else "medium"
            }
    
    # Перевіряємо "Німеччина" без конкретного міста
    if "deutschland" in text or "germany" in text or "🇩🇪" in text:
        return {
            "matched": False,
            "city": "Germany (not Frankfurt region)",
            "confidence": "low"
        }
    
    return {
        "matched": False,
        "city": None,
        "confidence": "none"
    }


def check_interest_match(bio: str, category: str = None) -> Dict:
    """
    Перевірити, чи профіль пов'язаний з ремонтом/кафелем.
    
    Args:
        bio: Біографія профілю
        category: Категорія бізнесу (якщо є)
        
    Returns:
        Dict: {matched: bool, keywords: List[str], score: int}
    """
    text = f"{bio or ''} {category or ''}".lower()
    matched_keywords = []
    
    # Перевіряємо німецькі ключові слова
    for keyword in KEYWORDS_DE:
        if keyword in text:
            matched_keywords.append(keyword)
    
    # Перевіряємо англійські
    for keyword in KEYWORDS_EN:
        if keyword in text:
            matched_keywords.append(keyword)
    
    # Рахуємо score
    score = len(matched_keywords) * 10
    
    # Бонуси за важливі слова
    high_value_words = ["fliesen", "fliesenleger", "badezimmer", "badsanierung", "renovierung"]
    for word in high_value_words:
        if word in matched_keywords:
            score += 15
    
    return {
        "matched": len(matched_keywords) > 0,
        "keywords": list(set(matched_keywords)),
        "score": min(score, 100)  # Максимум 100
    }


def get_search_hashtags(category: str = "all") -> List[str]:
    """
    Отримати список хештегів для пошуку.
    
    Args:
        category: "tiles", "bathroom", "renovation", "region", "all"
        
    Returns:
        List[str]: Список хештегів
    """
    if category == "tiles":
        return [h for h in HASHTAGS_SEARCH if "fliesen" in h or "tile" in h]
    elif category == "bathroom":
        return [h for h in HASHTAGS_SEARCH if "bad" in h or "bathroom" in h]
    elif category == "renovation":
        return [h for h in HASHTAGS_SEARCH if "renovierung" in h or "sanierung" in h or "handwerk" in h]
    elif category == "region":
        return [h for h in HASHTAGS_SEARCH if any(city in h for city in ["frankfurt", "offenbach", "darmstadt", "mainz", "wiesbaden", "rheinmain"])]
    else:
        return HASHTAGS_SEARCH


def get_suggested_accounts_keywords() -> List[str]:
    """
    Отримати ключові слова для пошуку схожих акаунтів.
    
    Returns:
        List[str]: Ключові слова для пошуку
    """
    return [
        "fliesenleger frankfurt",
        "badsanierung frankfurt",
        "renovierung frankfurt",
        "handwerker frankfurt",
        "fliesen rhein-main",
        "badezimmer design frankfurt",
        "innenausbau frankfurt",
        "bodenleger frankfurt",
    ]


def analyze_profile_relevance(username: str, bio: str, location: str = None, 
                              category: str = None, followers_count: int = 0) -> Dict:
    """
    Повний аналіз релевантності профілю.
    
    Returns:
        Dict: {
            relevant: bool,
            location_match: Dict,
            interest_match: Dict,
            total_score: int,
            recommendation: str
        }
    """
    location_result = check_location_match(bio, location)
    interest_result = check_interest_match(bio, category)
    
    # Загальний score
    total_score = 0
    
    # Локація
    if location_result["matched"]:
        if location_result["confidence"] == "high":
            total_score += 40
        elif location_result["confidence"] == "medium":
            total_score += 25
    
    # Інтереси
    total_score += interest_result["score"] // 2  # До 50 балів
    
    # Бонус за кількість підписників (популярні акаунти)
    if 1000 <= followers_count <= 50000:
        total_score += 10  # Ідеальний розмір для B2C
    elif followers_count > 50000:
        total_score += 5   # Великий, можливо менш таргетований
    
    # Визначаємо рекомендацію
    if total_score >= 60:
        recommendation = "🔥 Високий пріоритет - ідеальний профіль!"
    elif total_score >= 40:
        recommendation = "✅ Хороший профіль - варто додати"
    elif total_score >= 20:
        recommendation = "⚡ Середній - перевірте вручну"
    else:
        recommendation = "⚪ Низький пріоритет"
    
    return {
        "relevant": total_score >= 30,
        "location_match": location_result,
        "interest_match": interest_result,
        "total_score": min(total_score, 100),
        "recommendation": recommendation
    }
