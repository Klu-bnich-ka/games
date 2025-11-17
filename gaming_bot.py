import requests
import os
import re
import random
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime, timedelta
import time
import json
import logging
import hashlib
from urllib.parse import urljoin
import sqlite3
from contextlib import contextmanager

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Настройки
BOT_TOKEN = os.environ['GAMING_BOT_TOKEN']
CHANNEL = os.environ['GAMING_CHANNEL_ID']

# Инициализация базы данных
def init_database():
    conn = sqlite3.connect('gaming_news.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_hash TEXT UNIQUE,
            game_company TEXT,
            title TEXT,
            sent_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hash ON sent_news(news_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON sent_news(sent_date)')
    conn.commit()
    conn.close()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect('gaming_news.db')
    try:
        yield conn
    finally:
        conn.close()

def is_news_sent(news_hash):
    """Проверяет, была ли новость уже отправлена"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM sent_news WHERE news_hash = ?', (news_hash,))
        return cursor.fetchone() is not None

def mark_news_sent(news_hash, game_company, title):
    """Помечает новость как отправленную"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO sent_news (news_hash, game_company, title) VALUES (?, ?, ?)',
                (news_hash, game_company, title[:200])
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def cleanup_old_news(days=5):
    """Очищает старые записи"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sent_news WHERE sent_date < datetime("now", ?)', (f"-{days} days",))
        conn.commit()

# Стили форматирования для игрового бота
class GamingTextStyler:
    @staticmethod
    def bold(text):
        return f"<b>{text}</b>"

    @staticmethod
    def italic(text):
        return f"<i>{text}</i>"

    @staticmethod
    def code(text):
        return f"<code>{text}</code>"

    @staticmethod
    def create_header(text, emoji="🎮"):
        return f"{emoji} {GamingTextStyler.bold(text.upper())}"

    @staticmethod
    def create_highlight(text):
        return f"✨ {text} ✨"

# Инициализация стилера
gaming_styler = GamingTextStyler()

# ИСТОЧНИКИ ИГРОВЫХ НОВОСТЕЙ
GAMING_SOURCES = [
    {'name': 'IGN Games', 'url': 'http://feeds.ign.com/ign/games-all', 'lang': 'en'},
    {'name': 'GameSpot', 'url': 'https://www.gamespot.com/feeds/game-news/', 'lang': 'en'},
    {'name': 'Polygon', 'url': 'https://www.polygon.com/rss/index.xml', 'lang': 'en'},
    {'name': 'Kotaku', 'url': 'https://kotaku.com/rss', 'lang': 'en'},
    {'name': 'PC Gamer', 'url': 'http://www.pcgamer.com/rss/', 'lang': 'en'},
    {'name': 'Rock Paper Shotgun', 'url': 'https://www.rockpapershotgun.com/feed/', 'lang': 'en'},
    {'name': 'Eurogamer', 'url': 'https://www.eurogamer.net/feed.php', 'lang': 'en'},
    {'name': 'Game Informer', 'url': 'https://www.gameinformer.com/news.xml', 'lang': 'en'},
    {'name': 'Destructoid', 'url': 'https://www.destructoid.com/feed/', 'lang': 'en'},
    {'name': 'Nintendo Life', 'url': 'http://www.nintendolife.com/feeds/latest', 'lang': 'en'},
    {'name': 'PlayStation Blog', 'url': 'https://blog.playstation.com/feed/', 'lang': 'en'},
    {'name': 'Xbox Wire', 'url': 'https://news.xbox.com/en-us/feed/', 'lang': 'en'},
]

# ИГРОВЫЕ КОМПАНИИ И ПРОЕКТЫ
GAMING_ENTITIES = [
    # Компании
    'Nintendo', 'Sony', 'Microsoft', 'Valve', 'Electronic Arts', 'Ubisoft', 'Activision', 
    'Blizzard', 'Square Enix', 'Capcom', 'Bandai Namco', 'Sega', 'Epic Games', 'CD Projekt',
    'Rockstar Games', 'Bethesda', 'Naughty Dog', 'FromSoftware', 'BioWare', 'Bungie',
    
    # Игры и франшизы
    'The Legend of Zelda', 'Mario', 'Halo', 'Call of Duty', 'Fortnite', 'Minecraft', 
    'GTA', 'Elden Ring', 'Cyberpunk 2077', 'Starfield', 'God of War', 'The Last of Us',
    'Final Fantasy', 'Resident Evil', 'Dark Souls', 'Overwatch', 'World of Warcraft',
    'Apex Legends', 'Valorant', 'League of Legends', 'Dota 2', 'Counter-Strike',
    'Battlefield', 'Assassin\'s Creed', 'Far Cry', 'Watch Dogs', 'The Witcher',
    'Fallout', 'Elder Scrolls', 'Doom', 'Animal Crossing', 'Pokémon', 'Metroid',
    'Street Fighter', 'Tekken', 'Sonic', 'Persona', 'Mass Effect', 'Dragon Age'
]

# Эмодзи для игровых тем
GAMING_EMOJIS = {
    # Компании
    'Nintendo': '🎮', 'Sony': '🎯', 'Microsoft': '⚡', 'Valve': '🔷',
    'Electronic Arts': '🎲', 'Ubisoft': '🏰', 'Activision': '🎯',
    'Blizzard': '❄️', 'Square Enix': '⚔️', 'Capcom': '🐉',
    
    # Игры
    'The Legend of Zelda': '🗡️', 'Mario': '🍄', 'Halo': '👑', 
    'Call of Duty': '🔫', 'Fortnite': '💣', 'Minecraft': '⛏️',
    'GTA': '🚗', 'Elden Ring': '💍', 'Cyberpunk 2077': '🔮',
    'Starfield': '🚀', 'God of War': '⚡', 'The Last of Us': '🧟',
    'Final Fantasy': '🎭', 'Resident Evil': '🧪', 'Dark Souls': '🔥',
    
    # Платформы
    'PlayStation': '🎯', 'Xbox': '🟩', 'PC': '🖥️', 'Switch': '🔴',
    
    # Общие
    'default': '🎮'
}

class GamingTranslator:
    def __init__(self):
        self.cache = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def translate_text(self, text):
        """Перевод игрового контента"""
        try:
            # Пробуем разные сервисы перевода
            url = "https://libretranslate.de/translate"
            data = {
                'q': text,
                'source': 'en',
                'target': 'ru',
                'format': 'text'
            }
            response = self.session.post(url, json=data, timeout=15)
            if response.status_code == 200:
                result = response.json()
                return result['translatedText']
        except Exception as e:
            logger.warning(f"Translation failed: {e}")

        # Fallback перевод для игровых терминов
        gaming_translations = {
            'release': 'релиз', 'gameplay': 'геймплей', 'trailer': 'трейлер',
            'update': 'обновление', 'patch': 'патч', 'DLC': 'DLC',
            'expansion': 'дополнение', 'season': 'сезон', 'battle pass': 'боевой пропуск',
            'early access': 'ранний доступ', 'beta': 'бета-тест', 'alpha': 'альфа-тест',
            'console': 'консоль', 'PC': 'ПК', 'exclusive': 'эксклюзив',
            'multiplayer': 'мультиплеер', 'singleplayer': 'одиночная игра',
            'co-op': 'кооператив', 'competitive': 'соревновательный',
            'graphics': 'графика', 'performance': 'производительность',
            'frame rate': 'частота кадров', 'resolution': 'разрешение',
            'announced': 'анонсирована', 'delayed': 'отложена', 'cancelled': 'отменена',
            'studio': 'студия', 'developer': 'разработчик', 'publisher': 'издатель',
            'review': 'обзор', 'score': 'оценка', 'metacritic': 'метакритик'
        }

        translated = text
        for en, ru in gaming_translations.items():
            translated = re.sub(rf'\b{en}\b', ru, translated, flags=re.IGNORECASE)
        
        return translated

    def generate_gaming_insight(self, entity, content):
        """Генерирует игровые инсайты"""
        content_lower = content.lower()
        
        # Определяем тип контента
        if any(word in content_lower for word in ['релиз', 'release', 'выход']):
            theme = 'release'
            templates = [
                f"🎉 {gaming_styler.bold('ВАЖНЫЙ РЕЛИЗ')}: Готовьтесь к выходу долгожданного проекта!",
                f"🚀 {gaming_styler.bold('ЗАПУСК')}: Игра выходит на все платформы с впечатляющим контентом.",
                f"📅 {gaming_styler.bold('ДАТА ВЫХОДА')}: Отметим в календаре - скоро начнется новая эра!",
            ]
        elif any(word in content_lower for word in ['обновление', 'update', 'патч', 'patch']):
            theme = 'update'
            templates = [
                f"🛠️ {gaming_styler.bold('ОБНОВЛЕНИЕ')}: Разработчики улучшают игровой опыт.",
                f"⚙️ {gaming_styler.bold('БАЛАНС')}: Патч приносит значительные изменения в геймплей.",
                f"🔧 {gaming_styler.bold('ФИКСЫ')}: Исправлены критические ошибки и добавлен новый контент.",
            ]
        elif any(word in content_lower for word in ['трейлер', 'trailer', 'геймплей', 'gameplay']):
            theme = 'trailer'
            templates = [
                f"🎬 {gaming_styler.bold('ЗРЕЛИЩНЫЙ ТРЕЙЛЕР')}: Видео демонстрирует потрясающую графику.",
                f"📹 {gaming_styler.bold('ГОРЯЧИЙ ГЕЙМПЛЕЙ')}: Новые кадры раскрывают механику игры.",
                f"👀 {gaming_styler.bold('ПЕРВЫЙ ВЗГЛЯД')}: Эксклюзивные материалы уже доступны.",
            ]
        elif any(word in content_lower for word in ['dlc', 'дополнение', 'expansion']):
            theme = 'dlc'
            templates = [
                f"🆕 {gaming_styler.bold('НОВЫЙ КОНТЕНТ')}: Дополнение расширяет вселенную игры.",
                f"🌟 {gaming_styler.bold('ДОПОЛНИТЕЛЬНАЯ ИСТОРИЯ')}: Игроки получат новые приключения.",
                f"💎 {gaming_styler.bold('ЭКСПАНШЕН')}: Масштабное обновление с уникальным сюжетом.",
            ]
        else:
            theme = 'general'
            templates = [
                f"🎯 {gaming_styler.bold('ИГРОВАЯ СЕНСАЦИЯ')}: Проект обещает стать хитом сезона.",
                f"🚀 {gaming_styler.bold('ТЕХНОЛОГИЧЕСКИЙ ПРОРЫВ')}: Инновации в игровом дизайне.",
                f"💫 {gaming_styler.bold('ТВОРЧЕСКИЙ ПОДХОД')}: Разработчики создают нечто уникальное.",
                f"🔥 {gaming_styler.bold('ОЖИДАЕМЫЙ ПРОЕКТ')}: Сообщество с нетерпением ждет новинку.",
            ]

        # Дополнительные факты
        gaming_facts = {
            'release': [
                "Ожидается высокий спрос среди игроков всех платформ.",
                "Предзаказы уже бьют рекорды в цифровых магазинах.",
                "Критики предрекают игре успех у аудитории.",
            ],
            'update': [
                "Изменения затронут баланс и мета-игру.",
                "Сообщество активно обсуждает новые фичи.",
                "Обновление также улучшит оптимизацию.",
            ],
            'trailer': [
                "Видео набрало миллионы просмотров за первые часы.",
                "Фанаты анализируют каждый кадр в поисках пасхалок.",
                "Трейлер получил положительные отзывы за визуал.",
            ],
            'dlc': [
                "Дополнение добавит десятки часов игрового времени.",
                "Разработчики учли пожелания сообщества.",
                "Новый контент раскроет неизвестные детали сюжета.",
            ],
            'general': [
                "Проект демонстрирует высокое качество производства.",
                "Игровая индустрия продолжает удивлять инновациями.",
                "Ожидается, что релиз задаст новые стандарты.",
            ]
        }

        main_insight = random.choice(templates)
        additional_fact = random.choice(gaming_facts.get(theme, gaming_facts['general']))
        
        return f"{main_insight} {additional_fact}"

# Инициализация переводчика
gaming_translator = GamingTranslator()

def parse_rss_date(date_string):
    """Парсит дату из RSS"""
    if not date_string:
        return None
        
    date_formats = [
        '%a, %d %b %Y %H:%M:%S %Z',
        '%a, %d %b %Y %H:%M:%S %z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
        '%d %b %Y %H:%M:%S'
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_string, fmt)
        except:
            continue
    
    try:
        parsed_time = feedparser._parse_date(date_string)
        if parsed_time:
            return datetime.fromtimestamp(time.mktime(parsed_time))
    except:
        pass
        
    return None

def is_recent_gaming_news(entry, max_hours_old=12):
    """Проверяет свежесть игровых новостей"""
    date_fields = ['published', 'updated', 'created', 'pubDate']
    news_date = None
    
    for field in date_fields:
        date_str = getattr(entry, field, None)
        if date_str:
            parsed_date = parse_rss_date(date_str)
            if parsed_date:
                news_date = parsed_date
                break
    
    if not news_date:
        return False
    
    now = datetime.now()
    time_diff = now - news_date
    hours_diff = time_diff.total_seconds() / 3600
    
    return hours_diff <= max_hours_old

def generate_gaming_news_hash(entry, entity):
    """Генерирует хэш для игровой новости"""
    content = f"{entry.title}_{entry.link}_{entity}"
    return hashlib.md5(content.encode()).hexdigest()

def extract_gaming_image(url):
    """Поиск изображений для игровых новостей"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        image_selectors = [
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image:src"]',
            'article img',
            '.wp-post-image',
            '.article-image img',
            '.post-image img',
            '.entry-content img',
            '.content img',
            'figure img',
            '.hero-image img',
            '.main-image img',
            '.featured-image img',
            '[class*="image"] img',
            'img[src*="large"]',
            'img[src*="medium"]',
            'img'
        ]
        
        candidates = []
        for selector in image_selectors:
            elements = soup.select(selector)
            for element in elements:
                if selector.startswith('meta'):
                    image_url = element.get('content', '')
                else:
                    image_url = element.get('src') or element.get('data-src') or element.get('data-lazy-src')
                
                if image_url and is_valid_gaming_image(image_url):
                    score = rate_gaming_image_quality(image_url, element)
                    candidates.append((image_url, score))
        
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_image = candidates[0][0]
            
            if best_image.startswith('//'):
                best_image = 'https:' + best_image
            elif best_image.startswith('/'):
                best_image = urljoin(url, best_image)
            
            logger.info("✅ Found gaming image")
            return best_image
            
    except Exception as e:
        logger.warning(f"Gaming image extraction error: {e}")
    
    return None

def is_valid_gaming_image(url):
    """Проверяет валидность игрового изображения"""
    if not url.startswith(('http://', 'https://')):
        return False
    
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    if not any(ext in url.lower() for ext in valid_extensions):
        return False
    
    excluded_terms = ['icon', 'logo', 'thumbnail', 'small', 'avatar', 'sprite']
    if any(term in url.lower() for term in excluded_terms):
        return False
    
    return True

def rate_gaming_image_quality(url, element):
    """Оценивает качество игрового изображения"""
    score = 0
    
    if element.name == 'meta':
        score += 100
    
    width = element.get('width', '')
    height = element.get('height', '')
    if width and height:
        try:
            w = int(''.join(filter(str.isdigit, str(width))))
            h = int(''.join(filter(str.isdigit, str(height))))
            if w > 400 and h > 300:
                score += 50
            if w > 800 and h > 600:
                score += 30
        except:
            pass
    
    quality_indicators = ['large', 'xlarge', 'original', 'full', 'main', 'hero', 'featured']
    for indicator in quality_indicators:
        if indicator in url.lower():
            score += 20
    
    return score

def generate_gaming_title(entity, content):
    """Генерирует заголовки для игровых новостей"""
    content_lower = content.lower()
    
    # Стили заголовков для игр
    style_templates = {
        'breaking': [
            f"{entity}: СРОЧНЫЕ НОВОСТИ",
            f"ЭКСКЛЮЗИВ: {entity} раскрывает детали",
            f"{entity} - ГЛАВНАЯ ИГРОВАЯ НОВОСТЬ ДНЯ",
        ],
        'announcement': [
            f"{entity} анонсирует новый проект",
            f"ОФИЦИАЛЬНО: {entity} представляет",
            f"{entity} готовит сюрприз для фанатов",
        ],
        'review': [
            f"{entity}: первые впечатления и обзоры",
            f"ОЦЕНКИ: {entity} получает рейтинги",
            f"{entity} в рецензиях критиков",
        ],
        'update': [
            f"{entity} выпускает масштабное обновление",
            f"ПАТЧ: {entity} меняет геймплей",
            f"{entity} - новые возможности в обновлении",
        ]
    }
    
    # Выбор стиля по содержанию
    if any(word in content_lower for word in ['анонс', 'announce', 'анонсирова']):
        style = 'announcement'
    elif any(word in content_lower for word in ['обзор', 'review', 'оценк']):
        style = 'review'
    elif any(word in content_lower for word in ['обновлен', 'update', 'патч']):
        style = 'update'
    else:
        style = 'breaking'
    
    templates = style_templates.get(style, style_templates['breaking'])
    
    # Дополнительные тематические заголовки
    if any(word in content_lower for word in ['трейлер', 'trailer']):
        templates += [
            f"ПОТРЯСАЮЩИЙ ТРЕЙЛЕР {entity}",
            f"{entity}: эксклюзивный геймплей",
            f"ВИЗУАЛЬНАЯ ФАНТАСТИКА: {entity}",
        ]
    elif any(word in content_lower for word in ['релиз', 'release', 'выход']):
        templates += [
            f"{entity} ВЫХОДИТ НА ВСЕХ ПЛАТФОРМАХ",
            f"ДОЛГОЖДАННЫЙ РЕЛИЗ: {entity}",
            f"{entity} - дата выхода назначена",
        ]
    
    return random.choice(templates)

def create_gaming_post(entity, content, image_url=None):
    """Создает пост для игровых новостей"""
    emoji = GAMING_EMOJIS.get(entity, GAMING_EMOJIS['default'])
    
    # Генерация заголовка
    title = generate_gaming_title(entity, content)
    
    # Перевод и улучшение контента
    translated_content = gaming_translator.translate_text(content)
    styled_content = enhance_gaming_content(translated_content, entity)
    
    # Генерация инсайта
    gaming_insight = gaming_translator.generate_gaming_insight(entity, content)
    
    # Форматы постов для игр
    post_formats = [
        # Формат 1: Новостной
        lambda: f"{emoji} {gaming_styler.create_header(title, '📰')}\n\n"
                f"🎯 {styled_content}\n\n"
                f"💡 {gaming_insight}\n\n"
                f"{'▬' * 35}\n\n"
                f"🎮 {gaming_styler.italic('Обсуждаем в комментариях!')}",
        
        # Формат 2: Игровой
        lambda: f"{emoji} {gaming_styler.create_header(title, '🎲')}\n\n"
                f"🚀 {styled_content}\n\n"
                f"🌟 {gaming_styler.create_highlight(gaming_insight)}\n\n"
                f"{'•' * 25}\n\n"
                f"👥 {gaming_styler.italic('Ваше мнение о новости?')}",
        
        # Формат 3: Технический
        lambda: f"{emoji} {gaming_styler.bold(title)}\n\n"
                f"📊 {styled_content}\n\n"
                f"🔍 {gaming_insight}\n\n"
                f"{'─' * 30}\n\n"
                f"💬 {gaming_styler.italic('Ждем ваши мысли!')}",
        
        # Формат 4: Комьюнити
        lambda: f"{emoji} {gaming_styler.create_header(title, '👥')}\n\n"
                f"📝 {styled_content}\n\n"
                f"🎪 {gaming_insight}\n\n"
                f"{'═' * 35}\n\n"
                f"🗣️ {gaming_styler.italic('Присоединяйтесь к обсуждению!')}"
    ]
    
    return random.choice(post_formats)()

def enhance_gaming_content(text, entity):
    """Улучшает стиль игрового контента"""
    # Игровые ключевые слова для выделения
    gaming_keywords = [
        'релиз', 'геймплей', 'трейлер', 'обновление', 'патч', 'DLC',
        'эксклюзив', 'консоль', 'ПК', 'мультиплеер', 'одиночная',
        'графика', 'производительность', 'частота кадров', 'разрешение',
        'анонс', 'отложен', 'отменен', 'студия', 'разработчик', 'издатель'
    ]
    
    for keyword in gaming_keywords:
        if keyword in text.lower():
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            text = pattern.sub(gaming_styler.bold(r'\g<0>'), text)
    
    # Выделяем игровую сущность
    if entity in text:
        text = text.replace(entity, gaming_styler.bold(entity))
    
    # Добавляем игровые эмодзи
    if any(word in text.lower() for word in ['релиз', 'выход']):
        text = "🚀 " + text
    elif any(word in text.lower() for word in ['трейлер', 'геймплей']):
        text = "🎬 " + text
    elif any(word in text.lower() for word in ['обновление', 'патч']):
        text = "🛠️ " + text
    
    return text

def send_gaming_telegram_post(post, image_url=None):
    """Отправляет игровой пост в Telegram"""
    try:
        if image_url:
            headers = {'User-Agent': 'Mozilla/5.0'}
            image_response = requests.get(image_url, headers=headers, timeout=10)
            if image_response.status_code == 200 and len(image_response.content) > 5000:
                url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto'
                data = {
                    'chat_id': CHANNEL,
                    'caption': post,
                    'parse_mode': 'HTML'
                }
                files = {'photo': ('gaming.jpg', image_response.content, 'image/jpeg')}
                response = requests.post(url, data=data, files=files, timeout=30)
                if response.status_code == 200:
                    logger.info("✅ Gaming post sent with image")
                    return True
        
        # Отправка без изображения
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        data = {
            'chat_id': CHANNEL,
            'text': post,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }
        response = requests.post(url, json=data, timeout=30)
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"❌ Gaming Telegram error: {e}")
        return False

def find_and_send_gaming_news_optimized():
    """Оптимизированный поиск для 30-минутного интервала"""
    random.shuffle(GAMING_SOURCES)
    
    logger.info("🎮 Quick search for fresh gaming news...")
    
    # Проверяем меньше источников для скорости
    sources_to_check = GAMING_SOURCES[:8]  # Только 8 источников
    
    for source in sources_to_check:
        try:
            logger.info(f"Quick check: {source['name']}")
            feed = feedparser.parse(source['url'])
            
            if not feed.entries:
                continue
                
            # Проверяем только самые свежие записи
            fresh_entries = []
            for entry in feed.entries[:8]:  # Только 8 записей
                if is_recent_gaming_news(entry, max_hours_old=12):  # Только 12 часов
                    fresh_entries.append(entry)
            
            if not fresh_entries:
                continue
                
            # Быстрая обработка
            for entry in fresh_entries[:3]:  # Только 3 записи
                title = getattr(entry, 'title', '')
                description = getattr(entry, 'description', '')
                link = getattr(entry, 'link', '')
                
                if not title:
                    continue
                
                # Быстрый поиск по игровым сущностям
                full_content = f"{title} {description}".lower()
                
                for entity in GAMING_ENTITIES[:30]:  # Только 30 сущностей
                    if entity.lower() in full_content:
                        news_hash = generate_gaming_news_hash(entry, entity)
                        if is_news_sent(news_hash):
                            continue
                        
                        logger.info(f"🎯 Quick process: {entity}")
                        
                        try:
                            image_url = extract_gaming_image(link)
                            original_content = f"{title}. {description}"
                            post = create_gaming_post(entity, original_content, image_url)
                            
                            if send_gaming_telegram_post(post, image_url):
                                mark_news_sent(news_hash, entity, title)
                                logger.info(f"🎉 Quick sent: {entity}")
                                return True
                                
                        except Exception as e:
                            logger.error(f"Quick error: {str(e)}")
                        
                        break
                        
        except Exception as e:
            continue
            
    return False

def send_gaming_curated_post():
    """Отправляет курируемый игровой пост"""
    logger.info("🎨 Creating curated gaming post...")
    
    entities = ['Nintendo', 'Sony', 'Microsoft', 'Valve', 'Ubisoft', 'CD Projekt']
    entity = random.choice(entities)
    
    curated_gaming_content = [
        f"{entity} анонсирует новый игровой проект с инновационным геймплеем.",
        f"Скоро выйдет долгожданное обновление от {entity} с новым контентом.",
        f"{entity} представляет революционные технологии в игровой индустрии.",
        f"Эксклюзивный релиз от {entity} готовится к запуску на всех платформах.",
        f"{entity} инвестирует в развитие игровых сервисов и экосистемы.",
    ]
    
    content = random.choice(curated_gaming_content)
    post = create_gaming_post(entity, content)
    
    if send_gaming_telegram_post(post):
        logger.info("✅ Curated gaming post sent!")
        return True
    
    return False

if __name__ == "__main__":
    # Инициализация базы
    init_database()
    cleanup_old_news(days=5)  # Очищаем чаще
    
    logger.info("🚀 Starting QUICK GAMING BOT (30min intervals)")
    start_time = time.time()
    
    # Используем оптимизированную версию
    success = find_and_send_gaming_news_optimized()
    
    if not success:
        logger.info("📝 No quick news, sending curated...")
        send_gaming_curated_post()
    
    execution_time = time.time() - start_time
    logger.info(f"⏱️ Quick execution: {execution_time:.2f}s")
    logger.info("✅ Gaming news bot finished!")
