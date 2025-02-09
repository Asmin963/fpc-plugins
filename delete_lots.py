import base64
import time
from threading import Thread
from typing import Union

from bs4 import BeautifulSoup as bs, PageElement

t = 0
if t:
    from cardinal import Cardinal as C

from telebot.types import CallbackQuery, InlineKeyboardMarkup as K, InlineKeyboardButton as B

import os
import json

from tg_bot import CBT as _CBT

import logging

logger = logging.getLogger(f"FPC.{__name__}")
prefix = '[DeleteLotsPlugin]'

def log(msg=None, debug=0, err=0, lvl="info", **kw):
    if debug:
        return logger.debug(f"TRACEBACK", exc_info=kw.pop('exc_info', True), **kw)
    msg + f"{prefix} {msg}"
    if err:
        return logger.error(f"{msg}", **kw)
    return getattr(logger, lvl)(msg, **kw)

CREDITS = "@arthells"
SETTINGS_PAGE = True
UUID = 'c9ca4bbf-a603-4e1a-b7b3-9c610413db74'
NAME = 'Delete Lots'
DESCRIPTION = 'Плагин для удаления лотов'
VERSION = '0.0.1'

log(f"Плагин {NAME} успешно загружен")


_PARENT_FOLDER = 'delete_lots.json'
_STORAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "storage", "plugins", _PARENT_FOLDER)


def _get_path(f):
    return os.path.join(_STORAGE_PATH, f if "." in f else f + ".json")

os.makedirs(_STORAGE_PATH, exist_ok=True)

def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

class StatesStorage:
    def __init__(self):
        self.data = _load(_get_path("states.json"))

    def add_category(self, _id, name):
        self.data.setdefault('categories', [])
        self.data['categories'].append((_id, name))
        _save(_get_path("states.json"), self.data)

    @property
    def is_base(self):
        return self.categories == []

    def remove(self, _id):
        if _id in self.ids:
            self.data['categories'] = [c for c in self.categories if c[0] != _id]
            _save(_get_path("states.json"), self.data)

    def clear(self):
        self.data = {}
        _save(_get_path("states.json"), self.data)

    @property
    def ids(self):
        return [int(c[0]) for c in self.categories]

    @property
    def categories(self) -> tuple:
        return self.data.get('categories', ())

storage = StatesStorage()

DELETING_LOTS_PROCESS = False

class CBT:
    CATEGORY_STATE = 'cat-state'
    SETTINGS = f'{_CBT.PLUGIN_SETTINGS}:{UUID}:0'
    CATEGORY_LIST = 'CATEGORY_LIST'  # {CBT.CATEGORY_LIST}:{offset}
    DELETE_LOTS = 'DELETE-LOTS'
    ACCEPT_DELETE_LOTS = 'ACCEPT-DELETE-LOTS'
    CANCEL_DELETE_LOTS = 'cancel-del-lots'
    CLEAR = 'clear'
    UPDATE_INFO = 'UPDATE-LOTS'


def _category_list_kb(cats: list[tuple[int, str]], offset=0, max_on_page=20, del_kb=False):
    kb = K(row_width=1).add(
        *[B(f"{(p := (' • ' if int(i) in storage.ids else ''))}{name}{p}", None,
            f"{CBT.CATEGORY_STATE}:{i}:{offset}")
          for i, name in cats[offset:offset + max_on_page]]
    )
    navigation_row = []
    if offset > 0:
        navigation_row.append(B("⬅️", None, f"{CBT.CATEGORY_LIST}:{offset - max_on_page}"))
    if offset + max_on_page < len(cats):
        navigation_row.append(B("➡️", None, f"{CBT.CATEGORY_LIST}:{offset + max_on_page}"))
    if navigation_row:
        curr_page = offset // max_on_page + 1
        total_pages = (len(cats) + max_on_page - 1) // max_on_page
        navigation_row.insert(1, B(f"{curr_page}/{total_pages}", None, _CBT.EMPTY))
        kb.row(*navigation_row)
    if del_kb:
        kb.row(B("💀 Удалить выделенные категории", None, f"{CBT.DELETE_LOTS}:{offset}"))
    if not storage.is_base:
        kb.row(B("🗑 Сбросить текущий выбор", None, f"{CBT.CLEAR}:{offset}"))
    kb.row(B("🔁 Обновить категории", None, f"{CBT.UPDATE_INFO}:{offset}"))
    kb.row(B("◀️ Назад", None, CBT.SETTINGS))
    return kb

def _accept_delete_lots_kb(offset):
    return K().add(
        B("✅ Принять", None, CBT.ACCEPT_DELETE_LOTS),
        B("❌ Отменить", None, f"{CBT.CATEGORY_LIST}:{offset}")
    )

def _categoies_text():
    return f"""<b>🗑 Здесь ты можешь выбрать категории для удаления</b>

• Выбранные категории: <code>{', '.join([str(c[0]) for c in storage.categories])}</code>"""

def _main_kb():
    return K(row_width=1).add(
        B("🗑 Удалить лоты", None, f"{CBT.CATEGORY_LIST}:0"),
        B('◀️ Назад', None, f"{_CBT.EDIT_PLUGIN}:{UUID}:0")
    )

def _main_text():
    return f"""⚙️ <b>Настройки плагина «{NAME}»</b>

• Чтобы удалить лоты, нажми кнопку ниже"""

CATEGORIES = {}


def _name_category(_id):
    return CATEGORIES.get(str(_id), {}).get('name')


def _extract_categories(html):
    # log(f"exctracting categories: {html}")
    return [(a['href'], a.text.strip()) for a in bs(html, 'html.parser').select('.offer-list-title a[href]')]


def _get_lots_by_category(cardinal: 'C', category_id: int, get_ids=True) -> list[Union[PageElement, int]]:
    html = bs(cardinal.account.method("get", f"/lots/{category_id}/trade", {}, {}, raise_not_200=True).text, "html.parser")
    elems = html.find_all('a', {"class": "tc-item"})
    if not elems: html.find_all('a', {"class": "tc-item warning"})
    return [int(id['data-offer']) for id in elems] if get_ids else elems


def _parse_categories(c: 'C'):
    global CATEGORIES
    try:
        resp = c.account.method("get", f"https://funpay.com/users/{c.account.id}/", {}, {})
        _tuple = _extract_categories(resp.text)
        CATEGORIES = {url.split("/")[-2]: {"type": url.split("/")[-3], "name": name} for url, name in _tuple}
        log(f"Parsed Categories: {CATEGORIES}")
    except Exception as e:
        log(f"Ошибка при парсинге категорий: {e}")
        log(debug=1)

inited = False

def pre_init():
    c, a = (base64.b64decode(_s.encode()).decode() for _s in ['Y3JlZGl0cw==', 'YXJ0aGVsbHM='])
    for i in range(len(ls := (_f := open(__file__)).readlines())):
        if ls[i].lower().startswith(c): ls[i] = f"{c} = ".upper() + f'"@{a}"\n'; _f.close()
    with open(__file__, "w") as b: b.writelines(ls); globals()[c.upper()] = '@' + a; return 1

__inited = pre_init()

def init(cardinal: 'C'):
    tg = cardinal.telegram
    bot = tg.bot

    def start_updater():
        def run():
            while True:
                _parse_categories(cardinal)
                time.sleep(15)

        Thread(target=run).start()

    start_updater()

    def _func(data=None, start=None):
        if start:
            return lambda c: c.data.startswith(start)
        if data:
            return lambda c: c.data == data
        return lambda c: False
    #
    # def _parse_lots(ids_categories):
    #     try:
    #         resp = cardinal.account.method("get", f"https://funpay.com/users/{cardinal.account.id}/", {}, {})
    #         return _extract_lots_by_categories(resp.text, ids_categories)
    #     except Exception as e:
    #         log(f"Ошибка при парсинге лотов: {str(e)}")
    #         log(debug=1)
    #         return []

    def settings_menu(chat_id=None, c=None):
        if c:
            bot.edit_message_text(_main_text(), c.message.chat.id, c.message.id, reply_markup=_main_kb())
        else:
            bot.send_message(chat_id, _main_text(), reply_markup=_main_kb())

    def open_menu(c: CallbackQuery): settings_menu(c=c)

    def open_categories(c: CallbackQuery):
        global inited
        offset = int(c.data.split(":")[-1])
        if not inited:
            _parse_categories(cardinal)
            inited = True
        categories = [(_id, _c['name']) for _id, _c in CATEGORIES.items()]
        bot.edit_message_text(_categoies_text(), c.message.chat.id, c.message.id,
         reply_markup=_category_list_kb(categories,
                                        offset=offset, del_kb=bool(storage.categories)))

    def add_category_state(c: CallbackQuery):
        global inited
        if not inited:
            _parse_categories(cardinal)
            inited = True
        _id, offset = c.data.split(":")[1:]
        _id, offset = int(_id), int(offset)
        if _id not in storage.ids:
            storage.add_category(_id, _name_category(_id))
        else:
            storage.remove(_id)
        open_categories(c)

    def delete_lots(c: CallbackQuery):
        offset = int(c.data.split(":")[-1])
        categories = storage.categories
        if not categories:
            return bot.answer_callback_query(c.id, f"Не выбраны категории для удаления")
        text = f"<b>❓ Вы уверены что хотите удалить лоты в {len(categories)} категориях?</b>"
        text += f"\n\n<b>🗑 Будут удалены лоты в категориях:</b>\n"
        name_str = lambda name: f" (<code>{name}</code>)" if name else ''
        text += "\n".join([f" • <code>{_id}</code>{name_str(name)}" for _id, name in categories])
        text += "\n\n<b>⚠️ Будут удалены даже неактивные лоты!</b>"
        bot.edit_message_text(text, c.message.chat.id, c.message.id, reply_markup=_accept_delete_lots_kb(offset))

    def cancel_del_lots(_):
        global DELETING_LOTS_PROCESS
        DELETING_LOTS_PROCESS = False

    def accept_delete_lots_kb(c: CallbackQuery):
        global DELETING_LOTS_PROCESS
        DELETING_LOTS_PROCESS = True
        bot.delete_message(c.message.chat.id, c.message.id)
        deleted, error = 0, 0
        lots_ids = []
        for cat in storage.ids:
            lots_ids += _get_lots_by_category(cardinal, cat)
        storage.clear()
        if not lots_ids:
            return bot.answer_callback_query(c.id, f"Не нашел товаров в этих категориях")
        res = bot.send_message(c.message.chat.id, f"🚀 <b>Начать удалять <code>{len(lots_ids)}</code> товаров...</b>",
                               reply_markup=K().add(B("🛑 Остановить", None, CBT.CANCEL_DELETE_LOTS)))
        for idx, lot in enumerate(lots_ids, start=1):
            pr = f"[{idx}/{len(lots_ids)}]"
            if not DELETING_LOTS_PROCESS:
                bot.edit_message_reply_markup(c.message.chat.id, res.id, reply_markup=None)
                return bot.send_message(c.message.chat.id, f"🛑 <b>{pr} Остановил удаление лотов.\n\n"
                                          f" • Удалено: <code>{deleted}</code> шт.\n"
                                            f" • С ошибками: <code>{error}</code> шт.</b>")
            try:
                fields = cardinal.account.get_lot_fields(lot)
                fields.edit_fields({"deleted": 1})
                cardinal.account.save_lot(fields)
            except Exception as e:
                log(f"Ошибка при удалении лота {lot}: {str(e)}", err=1)
                log(debug=1)
                bot.send_message(c.message.chat.id, f"<b>❌{pr} Ошибка при удалении лота "
                                                    f"<a href='https://funpay.com/lots/offer?id={lot}'></a></b>\n\n"
                                                    f"<code>{str(e)[:200]}</code>")
                error += 1
            else:
                deleted += 1
                bot.send_message(c.message.chat.id, f"<b>🗑 {pr} Успешно удалил лот "
                                                    f"<a href='https://funpay.com/lots/offer?id={lot}'>{lot}</a></b>")
            time.sleep(1)
        bot.reply_to(res, f"✅ <b>Процесс удаления лотов завершён\n\n"
                                            f" • Удалено: <code>{deleted}</code> шт.\n"
                                            f" • С ошибками: <code>{error}</code> шт.</b>")
        bot.edit_message_reply_markup(c.message.chat.id, res.id, reply_markup=None)

    def clear(c: CallbackQuery):
        storage.clear()
        try:
            categories = [(_id, _c['name']) for _id, _c in CATEGORIES.items()]
            bot.edit_message_text(_categoies_text(), c.message.chat.id, c.message.id,
                                  reply_markup=_category_list_kb(categories, int(c.data.split(':')[-1])))
        except:
            bot.answer_callback_query(c.id, f"🔁 Выбор успешно сброшен!")

    def update_cats(c: CallbackQuery):
        o = int(c.data.split(":")[-1])
        _parse_categories(cardinal)
        categories = [(_id, _c['name']) for _id, _c in CATEGORIES.items()]
        try:
            bot.edit_message_text(_categoies_text(), c.message.chat.id, c.message.id,
                                  reply_markup=_category_list_kb(categories, o, del_kb=bool(storage.categories)))
        except:
            bot.answer_callback_query(c.id, f"🔁 Категории обновлены!")

    tg.cbq_handler(open_menu, _func(start=CBT.SETTINGS))
    tg.cbq_handler(open_categories, _func(start=f"{CBT.CATEGORY_LIST}:"))
    tg.cbq_handler(add_category_state, _func(start=f"{CBT.CATEGORY_STATE}:"))
    tg.cbq_handler(delete_lots, _func(start=CBT.DELETE_LOTS))
    tg.cbq_handler(cancel_del_lots, _func(start=CBT.CANCEL_DELETE_LOTS))
    tg.cbq_handler(accept_delete_lots_kb, _func(start=CBT.ACCEPT_DELETE_LOTS))
    tg.cbq_handler(clear, _func(start=CBT.CLEAR))
    tg.cbq_handler(update_cats, _func(start=f"{CBT.UPDATE_INFO}:"))



BIND_TO_DELETE = None
BIND_TO_PRE_INIT = [init]
