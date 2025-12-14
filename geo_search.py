"""
Модуль автоматичного пошуку схожих сторінок та геолокації.
Для пошуку цільової аудиторії в Instagram.
"""
from typing import List, Dict, Optional, Set, Any
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


# ============ DEFAULT GEO CONFIG (customizable per user) ============

DEFAULT_REGION_NAME = 'Frankfurt'
DEFAULT_RADIUS_KM = 100
DEFAULT_POSTAL_CODE_REGEX = r'\b(6[0-5]\d{3})\b'

DEFAULT_HIGH_CONFIDENCE_CITIES = ["frankfurt", "offenbach", "darmstadt", "mainz", "wiesbaden"]

DEFAULT_PRIORITY_HASHTAGS = [
    'fliesenleger', 'fliesen', 'badsanierung',
    'frankfurtammain', 'renovierung', 'handwerker'
]

DEFAULT_SUGGESTED_KEYWORDS = [
    "fliesenleger frankfurt",
    "badsanierung frankfurt",
    "renovierung frankfurt",
    "handwerker frankfurt",
    "fliesen rhein-main",
    "badezimmer design frankfurt",
    "innenausbau frankfurt",
    "bodenleger frankfurt",
]


def get_default_geo_config() -> Dict[str, Any]:
    return {
        'region_name': DEFAULT_REGION_NAME,
        'radius_km': DEFAULT_RADIUS_KM,
        'region_cities': list(FRANKFURT_REGION_CITIES),
        'postal_code_regex': DEFAULT_POSTAL_CODE_REGEX,
        'high_confidence_cities': list(DEFAULT_HIGH_CONFIDENCE_CITIES),
        'priority_hashtags': list(DEFAULT_PRIORITY_HASHTAGS),
        'suggested_keywords': list(DEFAULT_SUGGESTED_KEYWORDS),
    }


def normalize_geo_config(geo_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = get_default_geo_config()
    if geo_config:
        for k, v in geo_config.items():
            if v is None:
                continue
            cfg[k] = v

    # Normalize lists
    cities = cfg.get('region_cities') or []
    if isinstance(cities, str):
        cities = [c.strip() for c in cities.replace(',', '\n').split('\n') if c.strip()]
    cfg['region_cities'] = [str(c).strip().lower() for c in cities if str(c).strip()]

    hi = cfg.get('high_confidence_cities') or []
    if isinstance(hi, str):
        hi = [c.strip() for c in hi.replace(',', '\n').split('\n') if c.strip()]
    cfg['high_confidence_cities'] = [str(c).strip().lower() for c in hi if str(c).strip()]

    ph = cfg.get('priority_hashtags') or []
    if isinstance(ph, str):
        ph = [c.strip() for c in ph.replace(',', '\n').split('\n') if c.strip()]
    cfg['priority_hashtags'] = [str(c).strip().lower().lstrip('#') for c in ph if str(c).strip()]

    sk = cfg.get('suggested_keywords') or []
    if isinstance(sk, str):
        sk = [c.strip() for c in sk.replace(',', '\n').split('\n') if c.strip()]
    cfg['suggested_keywords'] = [str(c).strip() for c in sk if str(c).strip()]

    # Basic scalars
    try:
        cfg['radius_km'] = int(cfg.get('radius_km') or DEFAULT_RADIUS_KM)
    except Exception:
        cfg['radius_km'] = DEFAULT_RADIUS_KM

    cfg['region_name'] = str(cfg.get('region_name') or DEFAULT_REGION_NAME).strip()[:120]
    cfg['postal_code_regex'] = str(cfg.get('postal_code_regex') or DEFAULT_POSTAL_CODE_REGEX).strip()[:160]

    return cfg


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


def check_location_match(bio: str, location: str = None, geo_config: Optional[Dict[str, Any]] = None) -> Dict:
    """
    Перевірити, чи профіль знаходиться в регіоні Франкфурта.
    
    Args:
        bio: Біографія профілю
        location: Локація з профілю (якщо є)
        
    Returns:
        Dict: {matched: bool, city: str or None, confidence: str}
    """
    cfg = normalize_geo_config(geo_config)
    text = f"{bio or ''} {location or ''}".lower()
    
    # Перевіряємо поштові індекси
    try:
        postal_match = re.search(cfg.get('postal_code_regex') or DEFAULT_POSTAL_CODE_REGEX, text)
    except re.error:
        postal_match = re.search(DEFAULT_POSTAL_CODE_REGEX, text)
    if postal_match:
        return {
            "matched": True,
            "city": f"PLZ {postal_match.group(1)}",
            "confidence": "high"
        }
    
    # Перевіряємо міста
    for city in (cfg.get('region_cities') or FRANKFURT_REGION_CITIES):
        if city in text:
            return {
                "matched": True,
                "city": city.title(),
                "confidence": "high" if city in (cfg.get('high_confidence_cities') or DEFAULT_HIGH_CONFIDENCE_CITIES) else "medium"
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


def get_search_hashtags(category: str = "all", geo_config: Optional[Dict[str, Any]] = None) -> List[str]:
    """Отримати список хештегів для пошуку.

    Args:
        category: "tiles", "bathroom", "renovation", "region", "all"
        geo_config: Optional overrides (per-user geo settings)

    Returns:
        List[str]: Список хештегів
    """
    cfg = normalize_geo_config(geo_config)
    if category == "tiles":
        return [h for h in HASHTAGS_SEARCH if "fliesen" in h or "tile" in h]
    elif category == "bathroom":
        return [h for h in HASHTAGS_SEARCH if "bad" in h or "bathroom" in h]
    elif category == "renovation":
        return [h for h in HASHTAGS_SEARCH if "renovierung" in h or "sanierung" in h or "handwerk" in h]
    elif category == "region":
        # If user configured priority hashtags, use them as the region set.
        if cfg.get('priority_hashtags'):
            return list(cfg['priority_hashtags'])
        return [h for h in HASHTAGS_SEARCH if any(city in h for city in ["frankfurt", "offenbach", "darmstadt", "mainz", "wiesbaden", "rheinmain"])]
    else:
        # For 'all': prefer putting configured priority hashtags first.
        if cfg.get('priority_hashtags'):
            merged = []
            seen = set()
            for h in list(cfg['priority_hashtags']) + list(HASHTAGS_SEARCH):
                hh = str(h).strip().lower().lstrip('#')
                if not hh or hh in seen:
                    continue
                seen.add(hh)
                merged.append(hh)
            return merged
        return HASHTAGS_SEARCH


def get_suggested_accounts_keywords(geo_config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Отримати ключові слова для пошуку схожих акаунтів.
    
    Returns:
        List[str]: Ключові слова для пошуку
    """
    cfg = normalize_geo_config(geo_config)
    return list(cfg.get('suggested_keywords') or DEFAULT_SUGGESTED_KEYWORDS)


def analyze_profile_relevance(username: str, bio: str, location: str = None,
                              category: str = None, followers_count: int = 0,
                              geo_config: Optional[Dict[str, Any]] = None) -> Dict:
    """Повний аналіз релевантності профілю."""
    location_result = check_location_match(bio, location, geo_config=geo_config)
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
