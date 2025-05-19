import logging
from collections import deque
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, User, Message
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
)
from bot_config import BOT_TOKEN, MAIN_ADMIN_ID, ALLOWED_CHAT_IDS

BOT_TOKEN = "7639599178:AAEXq1WGeXLDM2puenT_yAos94x8u9BpcTg"
MAIN_ADMIN_ID = 1989336805
ALLOWED_CHAT_IDS = [-1002531648938]
INFO_REPORT_CHAT_ID = -1002652263518
ALERT_CHAT_ID = -1002652263518
KEYWORDS = ["ключевое", "пример", "alert", "дебил"]

active_mutes = {}
last_messages = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def keyword_and_spam_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    msg_id = update.message.message_id

    # --- Ключевые слова ---
    if any(word in text for word in KEYWORDS):
        try:
            await update.message.forward(ALERT_CHAT_ID)
        except Exception as e:
            await context.bot.send_message(MAIN_ADMIN_ID, f"❗ Ошибка при пересылке: {e}")

    # --- СПАМ: три одинаковых подряд ---
    # Инициализация очереди для чата
    if chat_id not in last_messages:
        last_messages[chat_id] = deque(maxlen=3)

    # Добавляем новое сообщение
    last_messages[chat_id].append((msg_id, text))

    # Если набралось 3, и все тексты одинаковы
    if len(last_messages[chat_id]) == 3:
        texts = [t for (_, t) in last_messages[chat_id]]
        if texts.count(texts[0]) == 3:
            # Пересылаем три последних сообщения
            for mid, _ in last_messages[chat_id]:
                try:
                    await context.bot.forward_message(
                        chat_id=ALERT_CHAT_ID,
                        from_chat_id=chat_id,
                        message_id=mid
                    )
                except Exception as e:
                    await context.bot.send_message(MAIN_ADMIN_ID, f"❗ Ошибка при спаме: {e}")

            # Оповещение о спаме
            await context.bot.send_message(ALERT_CHAT_ID, "В ЧАТЕ ОБНАРУЖЕН СПАМ")
            # Очистить очередь, чтобы не триггерить на каждое новое
            last_messages[chat_id].clear()

def parse_duration(duration_str):
    units = {'m': 60, 'h': 3600, 'd': 86400}
    try:
        unit = duration_str[-1]
        value = int(duration_str[:-1])
        if unit not in units:
            return None
        return value * units[unit]
    except Exception:
        return None

default_permissions = ChatPermissions(
    can_send_messages=True,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False
)

async def unmute_user(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    user_id = job_data["user_id"]
    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False
    )
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )
        await context.bot.send_message(
            MAIN_ADMIN_ID,
            f"✅ С пользователя {user_id} снят мут в чате {chat_id}."
        )
        active_mutes.pop(user_id, None)
    except Exception as e:
        await context.bot.send_message(MAIN_ADMIN_ID, f"❗ Ошибка при снятии мута: {e}")

async def get_user_by_username(bot, chat_id, username):
    try:
        async for member in bot.get_chat_administrators(chat_id):
            if member.user.username and member.user.username.lower() == username.lower():
                return member.user
        async for member in bot.get_chat_members(chat_id, limit=200):
            if member.user.username and member.user.username.lower() == username.lower():
                return member.user
        return None
    except Exception:
        return None

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    admins = [admin.user.id for admin in await context.bot.get_chat_administrators(update.effective_chat.id)]
    if update.effective_user.id not in admins:
        await update.message.delete()
        return

    if len(context.args) < 3:
       # await update.message.reply_text("Формат: /mute <user_id|@username> <срок> <причина>")
        await update.message.delete()
        return

    user_arg = context.args[0]
    user: User = None
    user_id = None

    if user_arg.startswith('@'):
        user = await get_user_by_username(context.bot, update.effective_chat.id, user_arg[1:])
        if not user:
           # await update.message.reply_text("❌ Юзернейм не найден в чате.")
            await update.message.delete()
            return
        user_id = user.id
    elif user_arg.isdigit():
        user_id = int(user_arg)
    else:
       # await update.message.reply_text("❌ Неверный user_id.")
        await update.message.delete()
        return

    # Теперь user_id точно валиден!
    member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
    old_permissions = getattr(member, "permissions", None)
    if old_permissions is None:
        old_permissions = ChatPermissions(can_send_messages=True)

    duration = parse_duration(context.args[1])
    reason = " ".join(context.args[2:])
    if not duration:
       # await update.message.reply_text("❌ Неверный формат срока. Пример: 30m, 2h, 1d")
        await update.message.delete()
        return

    until_date = datetime.utcnow() + timedelta(seconds=duration)
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        context.application.job_queue.run_once(
            unmute_user, duration, data={
                "chat_id": update.effective_chat.id,
                "user_id": user_id,
                "old_permissions": old_permissions
            }
        )
        active_mutes[user_id] = {
            "chat_id": update.effective_chat.id,
            "unmute_time": until_date,
            "reason": reason,
            "by": update.effective_user.id,
            "old_permissions": old_permissions
        }
        await context.bot.send_message(
            MAIN_ADMIN_ID,
            f"🔇 Мут выдан:\n"
            f"Пользователь: {user_id}\n"
            f"Чат: {update.effective_chat.id}\n"
            f"Срок: {context.args[1]}\n"
            f"Причина: {reason}\n"
            f"Кто выдал: {update.effective_user.id}\n"
            f"До: {until_date.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
       # await update.message.reply_text("✅ Мут выдан.")
    except Exception as e:
       # await update.message.reply_text(f"Ошибка: {e}")
        await context.bot.send_message(MAIN_ADMIN_ID, f"❗ Ошибка при выдаче мута: {e}")
    finally:
        await update.message.delete()

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем список id админов чата
    admins = [admin.user.id for admin in await context.bot.get_chat_administrators(update.effective_chat.id)]
    if update.effective_user.id not in admins:
        await update.message.delete()
        return

    if not update.message.reply_to_message:
        await update.message.delete()
        return
    target_msg: Message = update.message.reply_to_message
    offender: User = target_msg.from_user
    user_id = offender.id
    username = f"@{offender.username}" if offender.username else "(без юзернейма)"
    await context.bot.send_message(
        INFO_REPORT_CHAT_ID,
        f"🚨 Нарушитель:\nID: {user_id}\nUsername: {username}"
    )
    await update.message.delete()

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("info", info))
    # Заменяем keyword_alert на новый:
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_and_spam_alert))
    application.run_polling()

if __name__ == "__main__":
    main()