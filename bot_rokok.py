import os
import sys
from datetime import datetime, date
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

# ==============================================================================
# 🔒 FITUR PENGUNCI SERVER RENDER
# ==============================================================================
# Render secara otomatis menetapkan variabel RENDER="true" di servernya.
# Jika dijalankan di PC/VS Code/Zed lokal, variabel ini TIDAK ADA,
# sehingga program akan langsung mematikan dirinya sendiri (EXIT).
IS_RENDER = os.getenv("RENDER")

if not IS_RENDER:
    print("\n" + "="*60)
    print("❌ AKSES DITOLAK!")
    print("Bot ini dikunci dan HANYA BISA DIJALANKAN DI SERVER RENDER RESMI.")
    print("Eksekusi dari VS Code / Zed / PC Lokal dibatalkan.")
    print("="*60 + "\n")
    sys.exit(1)
# ==============================================================================

# Simpan status sesi izin yang aktif
active_sessions = {}

# Dictionary untuk melacak jumlah pelanggaran overtime harian per user
# Format: { user_id: {"date": date(2026, 8, 2), "count": 2, "banned": False} }
overtime_penalties = {}

# Durasi maksimal dalam detik (600 detik = 10 menit)
SMOKE_TIME_LIMIT = 600   # 10 menit untuk merokok
EAT_TIME_LIMIT = 600     # 10 menit untuk ambil makan

# Interval alarm berulang jika melebihi waktu (setiap 2 menit / 120 detik)
ALARM_INTERVAL_SECONDS = 120

# 🔗 URL Web App Google Apps Script Kamu
GOOGLE_SHEET_URL = "https://script.google.com/macros/s/AKfycbzQq-9Q8o0CJd-eBaKANsTjiDiidJgPH6i3HwRWHXwHu-NZJGHM5HKaRExtVjTKs2Ot/exec"


def send_to_google_sheet(user_id, name, permission_type, duration_str, is_overtime, duration_seconds, time_limit):
    """Mengirim data riwayat izin ke Google Sheets otomatis beserta durasi overtime-nya."""
    if not GOOGLE_SHEET_URL or GOOGLE_SHEET_URL == "PASTE_URL_WEB_APP_KAMU_DI_SINI":
        print("⚠️ Warning: URL Google Sheets belum diganti!")
        return

    overtime_str = "0m 0s"
    if is_overtime:
        overtime_secs = duration_seconds - time_limit
        ot_mins, ot_secs = divmod(overtime_secs, 60)
        overtime_str = f"{ot_mins}m {ot_secs}s"

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": name,
        "user_id": str(user_id),
        "type": permission_type,
        "duration": duration_str,
        "overtime": "YA" if is_overtime else "TIDAK",
        "overtime_duration": overtime_str,
    }

    try:
        response = requests.post(GOOGLE_SHEET_URL, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"✅ Data {name} ({permission_type}) berhasil dikirim ke Google Sheets!")
        else:
            print(f"⚠️ Gagal mengirim data. Status code: {response.status_code}")
    except Exception as e:
        print(f"❌ Error mengirim data ke Google Sheets: {e}")


def get_main_keyboard():
    """Mengembalikan susunan tombol menu utama."""
    keyboard = [
        [
            InlineKeyboardButton("🚬 Izin Merokok", callback_data="start_smoke"),
            InlineKeyboardButton("🍱 Izin Ambil Makan", callback_data="start_eat"),
        ],
        [
            InlineKeyboardButton("✅ Selesai & Kembali", callback_data="stop_permission"),
        ],
        [
            InlineKeyboardButton("📊 Cek Status Aktif", callback_data="check_status"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan menu utama bot."""
    await update.message.reply_text(
        "👋 *Selamat datang di Bot Izin Kerja!*\n\n"
        "• 🚬 *Izin Merokok:* Batas waktu 10 menit.\n"
        "• 🍱 *Izin Ambil Makan:* Batas waktu 10 menit.\n\n"
        "⚠️ *Perhatian:* Jika Anda melakukan *overtime* hingga 4 kali dalam sehari, Anda akan dikenakan sanksi tidak boleh mengambil izin (Merokok & Ambil Makan) selama sisa jam kerja hari ini!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


async def repeating_alarm(context: ContextTypes.DEFAULT_TYPE):
    """Alarm berulang jika overtime."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    user_name = job_data["name"]

    if user_id in active_sessions:
        p_type = active_sessions[user_id]["type"]
        limit_mins = active_sessions[user_id]["limit_mins"]
        start_time = active_sessions[user_id]["start_time"]
        dur = datetime.now() - start_time
        mins, secs = divmod(dur.seconds, 60)

        alarm_msg = (
            f"⏰ 🚨 *ALARM OVERTIME! SEGERA KEMBALI!* 🚨\n\n"
            f"🔔 Panggilan untuk [{user_name}](tg://user?id={user_id})!\n"
            f"Durasi *{p_type}* Anda sudah *{mins} menit {secs} detik* (Lewat Batas {limit_mins} Menit)!\n\n"
            f"Harap segera kembali dan tekan tombol *✅ Selesai & Kembali*!"
        )

        try:
            await context.bot.send_message(chat_id=chat_id, text=alarm_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Gagal kirim alarm ke grup: {e}")

        if chat_id != user_id:
            try:
                await context.bot.send_message(chat_id=user_id, text=alarm_msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Gagal kirim alarm ke private chat: {e}")


async def timeout_warning(context: ContextTypes.DEFAULT_TYPE):
    """Peringatan awal saat tepat batas waktu habis."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    user_name = job_data["name"]

    if user_id in active_sessions:
        p_type = active_sessions[user_id]["type"]
        limit_mins = active_sessions[user_id]["limit_mins"]

        warning_msg = (
            f"⏰ 🚨 *PERINGATAN WAKTU HABIS! ({limit_mins} MENIT)*\n\n"
            f"Halo [{user_name}](tg://user?id={user_id}), waktu *{p_type}* Anda sudah pas **{limit_mins} menit**!\n"
            f"Mohon segera kembali ke ruangan dan tekan tombol *✅ Selesai & Kembali*.\n\n"
            f"⚠️ *Alarm pengingat akan berulang setiap 2 menit sampai Anda kembali.*"
        )

        try:
            await context.bot.send_message(chat_id=chat_id, text=warning_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Gagal kirim peringatan ke grup: {e}")

        if chat_id != user_id:
            try:
                await context.bot.send_message(chat_id=user_id, text=warning_msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Gagal kirim peringatan ke private chat: {e}")

        alarm_job = context.job_queue.run_repeating(
            repeating_alarm,
            interval=ALARM_INTERVAL_SECONDS,
            first=ALARM_INTERVAL_SECONDS,
            data=job_data,
            name=f"alarm_{user_id}",
        )
        active_sessions[user_id]["alarm_job"] = alarm_job


async def safe_edit_message(query, text, reply_markup):
    """Fungsi pembantu untuk mengedit pesan."""
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani setiap klik tombol."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    user_name = user.first_name
    chat_id = query.message.chat_id
    reply_markup = get_main_keyboard()
    today = date.today()

    # Cek & reset data sanksi jika sudah berganti hari
    if user_id in overtime_penalties:
        if overtime_penalties[user_id]["date"] != today:
            overtime_penalties[user_id] = {"date": today, "count": 0, "banned": False}
    else:
        overtime_penalties[user_id] = {"date": today, "count": 0, "banned": False}

    # 1. Mulai Izin Merokok atau Ambil Makan
    if query.data in ["start_smoke", "start_eat"]:
        is_smoke = query.data == "start_smoke"

        # Cek apakah user terkena sanksi banned izin hari ini
        if overtime_penalties[user_id].get("banned", False):
            text = (
                f"❌ *SANKSI AKTIF!*\n\n"
                f"Maaf *{user_name}*, Anda sudah melakukan *overtime* sebanyak **4 kali** hari ini.\n"
                f"Anda dikenakan sanksi **tidak bisa mengambil izin (Merokok & Ambil Makan) selama sisa jam kerja hari ini**."
            )
            await safe_edit_message(query, text, reply_markup)
            return

        if user_id in active_sessions:
            current_type = active_sessions[user_id]["type"]
            start_time = active_sessions[user_id]["start_time"].strftime("%H:%M:%S")
            text = (
                f"⚠️ *{user_name}*, Anda sudah terdaftar sedang **{current_type}** sejak pukul **{start_time}**!\n\n"
                f"Tekan tombol 'Selesai & Kembali' jika sudah masuk ruangan."
            )
            await safe_edit_message(query, text, reply_markup)
        else:
            permission_type = "Izin Merokok" if is_smoke else "Izin Ambil Makan"
            time_limit = SMOKE_TIME_LIMIT if is_smoke else EAT_TIME_LIMIT
            limit_mins = 10

            job = context.job_queue.run_once(
                timeout_warning,
                when=time_limit,
                data={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "name": user_name,
                },
                name=f"timer_{user_id}",
            )

            active_sessions[user_id] = {
                "name": user_name,
                "type": permission_type,
                "time_limit": time_limit,
                "limit_mins": limit_mins,
                "start_time": datetime.now(),
                "job": job,
                "alarm_job": None,
            }
            time_str = active_sessions[user_id]["start_time"].strftime("%H:%M:%S")

            icon = "🚬" if is_smoke else "🍱"
            text = (
                f"{icon} *{permission_type} Diterima!*\n\n"
                f"👤 Nama: *{user_name}*\n"
                f"⏰ Jam Mulai: *{time_str}*\n"
                f"⏳ Batas Waktu: *{limit_mins} Menit*\n\n"
                f"Sesi Anda akan otomatis dicatat ke Google Sheets saat selesai."
            )
            await safe_edit_message(query, text, reply_markup)

    # 2. Selesai & Kembali
    elif query.data == "stop_permission":
        if user_id not in active_sessions:
            text = f"❓ *{user_name}*, Anda tidak memiliki sesi izin yang aktif."
            await safe_edit_message(query, text, reply_markup)
        else:
            session = active_sessions[user_id]

            # Hentikan timer & alarm
            job = session.get("job")
            if job:
                try:
                    job.schedule_removal()
                except Exception:
                    pass

            alarm_job = session.get("alarm_job")
            if alarm_job:
                try:
                    alarm_job.schedule_removal()
                except Exception:
                    pass

            for j in context.job_queue.get_jobs_by_name(f"alarm_{user_id}"):
                try:
                    j.schedule_removal()
                except Exception:
                    pass

            for j in context.job_queue.get_jobs_by_name(f"timer_{user_id}"):
                try:
                    j.schedule_removal()
                except Exception:
                    pass

            start_time = session["start_time"]
            permission_type = session["type"]
            time_limit = session["time_limit"]

            end_time = datetime.now()
            duration = end_time - start_time

            minutes, seconds = divmod(duration.seconds, 60)
            duration_str = f"{minutes}m {seconds}s"
            is_overtime = duration.seconds > time_limit

            # Catat hitungan overtime jika melebihi batas (4 kali)
            sanction_msg = ""
            if is_overtime:
                overtime_penalties[user_id]["count"] += 1
                current_count = overtime_penalties[user_id]["count"]

                if current_count >= 4:
                    overtime_penalties[user_id]["banned"] = True
                    sanction_msg = (
                        f"\n\n🚨 **SANKSI DIKELUARKAN!**\n"
                        f"Anda sudah melakukan *overtime* sebanyak **{current_count} kali** hari ini. "
                        f"Anda dikenakan sanksi **tidak bisa mengambil izin (Merokok & Ambil Makan) selama sisa jam kerja hari ini**!"
                    )
                else:
                    sanction_msg = f"\n⚠️ *Catatan:* Melebihi batas waktu! (Overtime ke-{current_count} hari ini)"

            # 📤 KIRIM DATA KE GOOGLE SHEETS
            send_to_google_sheet(
                user_id,
                user_name,
                permission_type,
                duration_str,
                is_overtime,
                duration.seconds,
                time_limit
            )

            del active_sessions[user_id]

            text = (
                f"✅ *Selesai / Kembali Bekerja*\n\n"
                f"👤 Nama: *{user_name}*\n"
                f"📋 Jenis: *{permission_type}*\n"
                f"⏱ Total Durasi: *{duration_str}*{sanction_msg}\n\n"
                f"📊 *Data berhasil dicatat ke Google Sheets!*"
            )
            await safe_edit_message(query, text, reply_markup)

    # 3. Cek Status Real-Time
    elif query.data == "check_status":
        if not active_sessions:
            text = "🟢 *Tidak ada yang sedang izin saat ini.* Semua ada di meja!"
        else:
            text = "📋 *Daftar Anggota yang Sedang Izin:*\n\n"
            now = datetime.now()
            for uid, data in active_sessions.items():
                dur = now - data["start_time"]
                mins, secs = divmod(dur.seconds, 60)
                status = "⚠️ (OVERTIME!)" if dur.seconds > data["time_limit"] else ""
                text += f"• *{data['name']}* - {data['type']} (Mulai: {data['start_time'].strftime('%H:%M:%S')} | Durasi: {mins}m {secs}s) {status}\n"

        await safe_edit_message(query, text, reply_markup)


def main():
    # Kamu juga bisa menyimpan TOKEN di Environment Variable Render (TELEGRAM_BOT_TOKEN)
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8866245372:AAH5UCzfGwRXqEZZRw5F5L_RgFaUwp5D5m8")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Server Render Terverifikasi. Bot Izin Kerja siap dijalankan...")
    app.run_polling()


if __name__ == "__main__":
    main()
