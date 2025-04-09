import asyncio
import re
from config.env import Config
from telethon import TelegramClient, events, errors
from telethon.tl import functions, types
import mysql.connector


def make_a_pool():
    connections = mysql.connector.connect(
        pool_name="pools",
        pool_size=5,
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        database=Config.DB_NAME,
    )

    return connections


pool = make_a_pool()


def get_db_connection() -> mysql.connector.MySQLConnection:
    # إعداد الاتصال بقاعدة البيانات
    db = mysql.connector.connect(pool_name="pools")

    if not db.is_connected():
        raise Exception("Unable To Connect To Database")

    return db


# إعداد معطيات تليجرام (استبدل api_id و api_hash بالقيم الخاصة بك)
api_id = Config.API_ID
api_hash = Config.API_HASH
OWNER_ID = Config.OWNER_ID

client = TelegramClient("bot_session", api_id, api_hash)


# دالة للتحقق من تفعيل البوت في المجموعة
async def is_group_activated(db: mysql.connector.MySQLConnection, group_id):
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT is_activated FROM tgroups WHERE group_id = %s", (group_id,))
    row = cursor.fetchone()
    return row and row[0]


# أمر تفعيل البوت (للمالك فقط)
@client.on(events.NewMessage(pattern="^تفعيل$"))
async def activate_handler(event):
    if event.sender_id != OWNER_ID:
        return  # تأكد من أن الأمر صادر عن مالك البوت
    group_id = event.chat_id

    db = get_db_connection()
    cursor = db.cursor(buffered=True)

    try:
        # إذا لم تكن المجموعة مسجلة مسبقًا في tgroups فقم بإدراجها
        cursor.execute(
            "INSERT IGNORE INTO tgroups (group_id, group_name, is_activated) VALUES (%s, %s, %s)",
            (group_id, event.chat.title if event.chat else "Unknown", True),
        )

        cursor.execute(
            "UPDATE tgroups SET is_activated = %s WHERE group_id = %s", (True, group_id)
        )
        db.commit()
        await event.reply(
            "✨ تم تفعيل نظام الدعوات!\n" "✅ الآن سيتم إنشاء روابط دعوة خاصة لكل عضو",
        )
    except Exception as e:
        print(e)
        await event.reply("خطأ أثناء تنفيذ الأمر")
    except mysql.connector.errors.OperationalError as ope_err:
        print(ope_err)
        pool = make_a_pool()
        await event.reply("عاود المحاولة بوقت لاحق")
    finally:
        cursor.close()
        db.close()


# أمر تعطيل البوت (للمالك فقط)
@client.on(events.NewMessage(pattern="^تعطيل$"))
async def deactivate_handler(event):
    if event.sender_id != OWNER_ID:
        return
    group_id = event.chat_id

    db = get_db_connection()
    cursor = db.cursor(buffered=True)

    try:
        # إذا لم تكن المجموعة مسجلة مسبقًا في tgroups فقم بإدراجها
        cursor.execute(
            "INSERT IGNORE INTO tgroups (group_id, group_name, is_activated) VALUES (%s, %s, %s)",
            (group_id, event.chat.title if event.chat else "Unknown", True),
        )

        cursor.execute(
            "UPDATE tgroups SET is_activated = %s WHERE group_id = %s",
            (False, group_id),
        )
        db.commit()
        await event.reply("تم تعطيل البوت في المجموعة.")
    except Exception as e:
        print(e)
        await event.reply("خطأ أثناء تنفيذ الأمر")
    except mysql.connector.errors.OperationalError as ope_err:
        print(ope_err)
        pool = make_a_pool()
        await event.reply("عاود المحاولة بوقت لاحق")
    finally:
        cursor.close()
        db.close()


# أمر رابط للمستخدمين
@client.on(events.NewMessage(pattern="^ا?ل?رابطي?$"))
async def mylink_handler(event: events.NewMessage.Event):
    sender = await event.get_sender()
    group_id = event.chat_id
    user_id = event.sender_id

    link_title = f"{sender.first_name}_{sender.username}_{user_id}"

    db = get_db_connection()

    # التحقق من تفعيل البوت في المجموعة
    if not await is_group_activated(db, group_id):
        return

    cursor = db.cursor(buffered=True)

    try:
        # البحث عن الرابط الخاص بالمستخدم
        cursor.execute(
            "SELECT link, joined_num FROM invitation_links WHERE user_id = %s AND group_id = %s",
            (user_id, group_id),
        )
        row = cursor.fetchone()
        if not row:
            # إنشاء رابط دعوة جديد إذا لم يكن موجوداً
            result = await client(
                functions.messages.ExportChatInviteRequest(
                    peer=group_id, title=link_title
                )
            )
            link = result.link
            joined_num = 0
            cursor.execute(
                "INSERT IGNORE INTO tusers (user_id, firstname) VALUES (%s, %s)",
                (user_id, sender.first_name),
            )
            cursor.execute(
                "INSERT INTO invitation_links (user_id, group_id, link, joined_num) VALUES (%s, %s, %s, %s)",
                (user_id, group_id, link, joined_num),
            )
            db.commit()
        else:
            link, joined_num = row

        await event.reply(
            "رابط الدعوة الخاص بك:\n"
            f"`{link}`\n\n"
            "- كل شخص ينضم عبر هذا الرابط يحسب لك\n"
            "- عند جلب 30 عضو ستصبح مشرفاً في المجموعة",
            parse_mode="markdown",
        )
    except Exception as e:
        print(e)
        await event.reply("حدث خطأ، لا يمكن الاستعلام عن رابطك الان")
    except mysql.connector.errors.OperationalError as ope_err:
        print(ope_err)
        pool = make_a_pool()
        await event.reply("عاود المحاولة بوقت لاحق")
    finally:
        cursor.close()
        db.close()


@client.on(
    events.NewMessage(
        pattern=r"^/revoke\s+https?://(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)([\w\-]+)"
    )
)
async def revoke_inviation_link_handler(event: events.NewMessage.Event):
    if event.sender_id != OWNER_ID:
        return

    group_id = event.chat_id
    link = event.pattern_match.group(1)

    if not link:
        return

    msg = "Not Completed"
    link = f"https://t.me/+{link}"

    try:
        await client(
            functions.messages.EditExportedChatInviteRequest(
                peer=group_id, link=link, revoked=True
            )
        )
        msg = "تم"
    except errors.RPCError as e:
        msg = "حدث خطأ"
        print(e)

    await event.reply(msg)


@client.on(
    events.NewMessage(
        pattern=r"^/delete\s+https?://(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)([\w\-]+)"
    )
)
async def delete_from_db_handler(event: events.NewMessage.Event):
    if event.sender_id != OWNER_ID:
        return

    group_id = event.chat_id
    link = event.pattern_match.group(1)

    if not link:
        return

    msg = "Not Completed"
    link = f"https://t.me/+{link}"

    db = get_db_connection()
    cursor = db.cursor(buffered=True)

    try:
        cursor.execute("DELETE FROM invitation_links WHERE link = %s", (link,))
        db.commit()
        msg = "تم"
    except errors.RPCError as e:
        msg = "حدث خطأ"
        db.rollback()
        print(e)
    except mysql.connector.errors.OperationalError as ope_err:
        print(ope_err)
        pool = make_a_pool()
        await event.reply("عاود المحاولة بوقت لاحق")
    finally:
        cursor.close()
        db.close()

    await event.reply(msg)


# تشغيل البوت
async def main():
    await client.start(bot_token=Config.BOT_TOKEN)
    print("The Bot is Running...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
