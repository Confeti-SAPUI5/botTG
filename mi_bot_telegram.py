from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler
from oauth2client.service_account import ServiceAccountCredentials
from telegram.ext.filters import BaseFilter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta
from pytz import timezone

import json
import os
import re
import gspread


TOKEN = '7627758916:AAErmy69sD3-NX6ITLmd1EY96Y_f2zSmllw'
admin_chat_id = 7525505749  # Reemplaza con el ID de tu chat
BD = 'BD BotTelegram'
user_states = {}

#Para identificase en Google Sheets
def get_google_client() :
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets", 'https://www.googleapis.com/auth/drive']
    google_credentials_str = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if google_credentials_str is None:
        raise ValueError("La variable de entorno 'GOOGLE_CREDENTIALS_JSON' no está configurada correctamente.")
    
    google_credentials = json.loads(google_credentials_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_credentials, scope)
    #Para probar en local:
    #google_credentials = 'credentials.json'
    #creds = ServiceAccountCredentials.from_json_keyfile_name(google_credentials, scope)
    return gspread.authorize(creds)

#Para recoger todos los registros de una hoja
async def get_google_sheet_data(sheet_id: int):
    googleClient = get_google_client()
    spreadsheet = googleClient.open(BD)
    sheet = spreadsheet.get_worksheet(sheet_id) 
    aData = sheet.get_all_records()
    return aData

#Para actualizar un registro en una hoja
async def update_google_sheet(worksheet_index, row, column, value):
    googleClient = get_google_client()
    sheet = googleClient.open(BD).get_worksheet(worksheet_index)
    sheet.update_cell(row, column, value)

#Para actualizar un varios registros en una hoja
async def update_google_sheet_batch(worksheet_index, start_row, start_col, data):
    googleClient = get_google_client()
    sheet = googleClient.open(BD).get_worksheet(worksheet_index)

    # Convertimos el inicio a rango A1
    start_cell = gspread.utils.rowcol_to_a1(start_row, start_col)

    # Calculamos el rango de destino según el tamaño de los datos
    end_cell = gspread.utils.rowcol_to_a1(start_row + len(data) - 1, start_col + len(data[0]) - 1)

    # Rango completo a actualizar
    range_ = f"{start_cell}:{end_cell}"

    # Actualizamos el rango con los valores
    sheet.update(range_, data)


#Funcion para validar si el usuario a mandado un correo
def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

#Verifica que el correo sea válido y esté en la BD
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    #Verificamos que el usuario esté en BD
    if not await checkUser(update):
        return
    
    user_message = update.message.text.strip()

    if user_states.get(user_id) == 'waiting_for_email':
        await replaceAccount(update, context, user_message)
        return

    if user_states.get(user_id) == 'waiting_for_saldo':
        await giveNewAccounts(update, context, user_message)
        return
    
    await update.message.reply_text(f"Utiliza los botones o el comando /start para continuar")

async def giveNewAccounts(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message) -> None:
    iSaldo = await get_saldo(update)
    try:
        cantidad = int(user_message)
        if cantidad > 0 and cantidad <= iSaldo:
            await update.message.reply_text(f"Has solicitado {cantidad} cuentas. Procesando...")
            await checkAvailableAccounts(update, context, cantidad)
            # Lógica adicional para otorgar cuentas
        else:
            await update.message.reply_text(f"Por favor, introduce un número positivo menor o igual a tu saldo ({iSaldo}).")
    except ValueError:
        await update.message.reply_text("Debes introducir un número válido.")
    return

async def checkAvailableAccounts(update, context, num_accounts):
    aAccounts = await get_google_sheet_data(1)

    # Filtrar las cuentas disponibles: Usuario (C) está vacío y Estado (D) no es "Error"
    available_accounts = [
        {"Correo": row["Correo"], "Contraseña": row["Contraseña"]}
        for row in aAccounts
        if not row["Usuario"] and row["Estado"] != "Error"
    ]

    # Verificar si hay suficientes cuentas disponibles
    if len(available_accounts) < num_accounts:
        await update.message.reply_text(
            f"Solo hay {len(available_accounts)} cuentas disponibles, pero solicitaste {num_accounts}."
        )
        return None
    
    extracted_accounts = available_accounts[:num_accounts]

    # Mostrar las cuentas al usuario
    message = "Las cuentas disponibles son:\n\n"
    for account in extracted_accounts:
        message += f"📧 Correo: {account['Correo']}\n🔑 Contraseña: {account['Contraseña']}\n\n"

    await update.message.reply_text(message)

    await updateAssignedAccounts(update, context, num_accounts, extracted_accounts)

async def updateAssignedAccounts(update, context, num_accounts, extracted_accounts):
    user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id
    aAccounts = await get_google_sheet_data(1)
    # Actualizar la columna C (Usuario) en la hoja 1 para las cuentas entregadas
    for account in extracted_accounts:
        account_email = account['Correo']
        await add_log(update, context, f'Cuenta {account_email} entregada gastando saldo')
        for i, row in enumerate(aAccounts):
            if row['Correo'] == account_email:
                await update_google_sheet(1, i + 2, 3, user_id)  # Actualiza la columna C con el user_id

    # Actualizar la columna C en la hoja 0 (saldo) restando las cuentas entregadas
    aUsers = await get_google_sheet_data(0)
    for user in aUsers:
        if user['ID'] == user_id:
            current_balance = user['saldo']
            if current_balance is not None:
                new_balance = current_balance - num_accounts
                await update_google_sheet(0, aUsers.index(user) + 2, 3, new_balance)  # Actualiza la columna C con el nuevo saldo
                break

async def verifyAccountStatus(update: Update, context: ContextTypes.DEFAULT_TYPE, aAccounts, sAccount) -> bool:
    for oAccount in aAccounts:
        if oAccount['Correo'].lower() == sAccount.lower() and oAccount['Estado'] == 'Error':
            await update.message.reply_text(f'Esta cuenta ya ha sido reportada')
            return False
    return True

async def verifyAccountUser(update: Update, context: ContextTypes.DEFAULT_TYPE, aAccounts, sAccount, iUserID) -> bool:
    iRow = 0
    for iIndex, oAccount in enumerate(aAccounts):
        if oAccount['Correo'].lower() == sAccount.lower() and oAccount['Usuario'] == iUserID:
            iRow = iIndex + 2
            break 
    return iRow
    
async def replaceAccount(update: Update, context: ContextTypes.DEFAULT_TYPE, user_message) -> None:
    user_id = update.message.from_user.id
    del user_states[user_id]
    
    #Verificamos que haya escrito un correo válido
    if not user_message or not is_valid_email(user_message):
        await update.message.reply_text("Por favor, introduce una dirección de correo válida.")
        return
    
    #Verificamos el número máximo de reportes
    if not await verifyUserMaxReports(update, False):
        return

    #Verificamos que la cuenta no esté en estado error (significaría que ya ha sido reporatada antes)
    aAccounts = await get_google_sheet_data(1)
    if not await verifyAccountStatus(update, context, aAccounts, user_message):
        return
    
    #Verificamos que la cuenta pertenece al usuario que la está reportando
    iRow = await verifyAccountUser(update, context, aAccounts, user_message, user_id)
    if iRow == 0:
        await update.message.reply_text(f"El correo '{user_message}' no se encuentra asociado a tu usuario")
        await context.bot.send_message(chat_id=admin_chat_id, text=f'El usuario {user_id} ha escrito: {user_message} y no se encuentra asociado a tu usuario')
        return

    await send_Netflix_replacement(update, context, iRow, user_message, user_id)

async def checkUser(update: Update) -> bool:
    user_id = update.message.from_user.id
    aData = await get_google_sheet_data(0)
    bFound = False
    for oData in aData:
        if oData['ID'] == user_id:
            bFound = True
            break
    return bFound

from datetime import datetime

async def notify_users(update, context):
    # Comprobar si el usuario que ejecuta la función es el admin
    user_id = update.message.from_user.id
    if user_id != admin_chat_id:
        await update.message.reply_text('No tienes permisos para usar este botón')
        return

    googleClient = get_google_client()
    sheet = googleClient.open(BD).get_worksheet(1)
    accounts = sheet.get_all_records()
    today = datetime.now().strftime("%d/%m/%Y")

    # Crear un diccionario para agrupar correos por usuario de Telegram
    user_accounts = {}

    for account in accounts:
        # Comprobar la fecha de renovación
        if account["Fecha renovación"]:
            renewal_date = datetime.strptime(account["Fecha renovación"], "%d/%m/%Y")
            if renewal_date.strftime("%d/%m/%Y") <= today:
                telegram_user = account["Usuario"]
                if telegram_user:
                    if telegram_user not in user_accounts:
                        user_accounts[telegram_user] = []
                    user_accounts[telegram_user].append(account["Correo"])

    # Enviar un mensaje por usuario con todas sus cuentas a renovar
    for telegram_user, emails in user_accounts.items():
        try:
            message = "Hola buenas 👋🙂\n\nLas siguientes cuentas necesitan renovación:\n"
            message += "\n".join(emails)
            await context.bot.send_message(chat_id=telegram_user, text=message)
        except Exception as e:
            print(f"Error al enviar mensaje a {telegram_user}: {e}")

    # Confirmar al admin que la tarea se realizó
    await update.message.reply_text("Se han enviado los mensajes a los usuarios correspondientes. ✅")

async def verifyUserMaxReports(update: Update, bDelete) -> bool:
    user_id = update.message.from_user.id
    aUsers = await get_google_sheet_data(0)
    iMaxReports = 0
    for oUser in aUsers:
        if oUser['ID'] == user_id:
            iMaxReports = oUser['maxReports']
            break
    
    aReports = await get_google_sheet_data(2)
    resultados_filtrados = [reporte for reporte in aReports if reporte['ID Usuario'] == user_id]
    if not len(resultados_filtrados):
        await update.message.reply_text("Has llegado al límite de reportes en 24h")
        return False
    
    if len(resultados_filtrados) >= iMaxReports:
        #Verificar si han pasado mas de 24h desde el último reporte, si es así borrarlo. Si no es asi dar aviso al usuario
        fechas = [
            datetime.strptime(reporte['Fecha reporte'], "%d/%m/%Y %H:%M:%S")
            for reporte in resultados_filtrados
            if reporte['Fecha reporte']  # Asegurarse de que la fecha no esté vacía
        ]
        fecha_mas_antigua = min(fechas)
        fecha_actual = datetime.now()
        if fecha_actual - fecha_mas_antigua > timedelta(hours=24):
            if bDelete:
                await borrar_reporte_mas_antiguo(aReports, user_id, resultados_filtrados)
            return True
        else:
            tiempo_24h = fecha_mas_antigua + timedelta(hours=24)
            tiempo_restante = tiempo_24h - fecha_actual
            horas, resto = divmod(tiempo_restante.total_seconds(), 3600)
            minutos, segundos = divmod(resto, 60)
            await update.message.reply_text("Has llegado al límite de reportes en 24h")
            await update.message.reply_text(f"Tiempo restante: {int(horas)} horas, {int(minutos)} minutos, {int(segundos)} segundos")
            return False
    if len(resultados_filtrados) < iMaxReports:
            return True

from datetime import datetime

async def borrar_reporte_mas_antiguo(aReports, user_id, registros_usuario):
    # Filtrar fechas válidas y convertirlas a objetos datetime
    fechas = [
        datetime.strptime(reporte['Fecha reporte'], "%d/%m/%Y %H:%M:%S")
        for reporte in registros_usuario
        if reporte['Fecha reporte']  # Asegurarse de que la fecha no esté vacía
    ]
    
    if not fechas:
        print("No se encontraron fechas válidas para este usuario.")
        return

    fecha_mas_antigua = min(fechas)
    
    # Encontrar el índice de la fila con la fecha más antigua para este usuario
    row_to_delete = None
    for index, reporte in enumerate(aReports):
        if (reporte['ID Usuario'] == user_id and 
            reporte['Fecha reporte'] and  # Asegura que la fecha no esté vacía
            datetime.strptime(reporte['Fecha reporte'], "%d/%m/%Y %H:%M:%S") == fecha_mas_antigua):
            row_to_delete = index + 2  # +2 porque las filas en Google Sheets comienzan en 1 y hay una fila de encabezado
            break

    # Borrar el contenido de las celdas correspondientes al registro más antiguo
    if row_to_delete:
        await update_google_sheet(2, row_to_delete, 1, "")  # Borrar ID Usuario
        await update_google_sheet(2, row_to_delete, 2, "")  # Borrar Fecha reporte
        print(f"Registro más antiguo del usuario {user_id} eliminado en la fila {row_to_delete}.")
    else:
        print("No se encontró el registro más antiguo para eliminar.")

async def send_Netflix_replacement(update, context, iRow, user_message, user_id) -> bool:
    aCuentas = await get_google_sheet_data(1)
    resultado, fila = next(
        ((obj, idx + 2) for idx, obj in enumerate(aCuentas) if obj['Usuario'] == '' and obj['Estado'] != 'Error'),
        (None, None)
    )

    if resultado:
        #Enviamos el reemplazo
        await update.message.reply_text(f"Reemplazo generado: \nCorreo: {resultado['Correo']}\nContraseña: {resultado['Contraseña']}")
        await add_log(update, context, f"{user_message} reemplazada por \n {resultado['Correo']}")

        #Rellenammos columna usuario de la cuenta que le hemos dado
        await update_google_sheet(1, fila, 3, user_id)

        #Rellenamos las columnas estado y ultimo usuario de la cuenta reportada
        await update_google_sheet(1, iRow, 4, 'Error')
        await update_google_sheet(1, iRow, 5, user_id)
        
        #Eliminamos el registro del reporte mas antiguo si han pasado mas de 24h
        await verifyUserMaxReports(update, True)

        #Añadimos el log del reemplazo de cuenta
        aReportes = await get_google_sheet_data(2)
        fecha_hoy = datetime.now()
        fecha_formateada = fecha_hoy.strftime("%d/%m/%Y %H:%M:%S")
        #await update_google_sheet(2, len(aReportes) + 2, 1, f"{user_id}\t{fecha_formateada}\t{user_message}\t{resultado['Correo']}")
        data = [[user_id, fecha_formateada, user_message, resultado['Correo']]]
        await update_google_sheet_batch(2, len(aReportes) + 2, 1, data)        
        return True
    else:
        await update.message.reply_text("No hay reemplazos disponibles, prueba mas tarde.")
        return False
    
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.callback_query.from_user.id
    if user_id != admin_chat_id:
        await update.message.reply_text('No tienes permisos para usar este botón')
        return
    
    keyboard = [
        [
            InlineKeyboardButton("🔴 Avisar renovaciones 🔴", callback_data="notify_users"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.reply_markup(reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await checkUser(update):
        await update.message.reply_text('No tienes permisos para usar este bot')
        await add_log(update, context, 'Usuario no autorizado intentado usar  el bot')
        return
    keyboard = [
        [
            InlineKeyboardButton("🔴 Reemplazo Netflix 🔴", callback_data="solicitar_correo"),
        ],
        [
            InlineKeyboardButton("🛍️ Solicitar cuentas 🛍️", callback_data="gastar_saldo")
        ],
        [
            InlineKeyboardButton("📥 Revisar saldo 📥", callback_data="ver_saldo")
        ],
        [
            #InlineKeyboardButton("💰 Precios 💰", callback_data="ver_precios"),
            InlineKeyboardButton("📞 Recargar saldo 📞", callback_data="ver_contacto")
        ],
        [
            InlineKeyboardButton("🛠️ Admin 🛠️", callback_data="admin_buttons")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f'Bienvenido al bot', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    # Confirmar el callback para que el botón no quede marcado
    await query.answer()

    if query.data == "solicitar_correo":
        await update.effective_message.reply_text("Introduce la dirección de correo electrónico que da error:")
        user_states[query.from_user.id] = 'waiting_for_email'

    elif query.data == "ver_contacto":
        await update.effective_message.reply_text(f'Para recargar contactar con @confeti')

    elif query.data == "ver_saldo":
        await ver_saldo(update)

    elif query.data == "gastar_saldo":
        await gastar_saldo(update)

    elif query.data == "admin_buttons":
        await admin_buttons(update, context)

            


async def add_log(update, context, sDetails) -> None:
    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    sMessage = f"Fecha: {fecha_actual}\n"
    sMessage = sMessage + f"Usuario: {update.message.from_user.id}\n"
    sMessage = sMessage + f"Detalles: {sDetails}"
    await context.bot.send_message(chat_id=admin_chat_id, text=f"{sMessage}")


async def ver_saldo(update: Update) -> None:
    user_id = update.callback_query.from_user.id
    aUsers = await get_google_sheet_data(0)
    for oUser in aUsers:
        if oUser['ID'] == user_id:
            iSaldo = oUser['saldo']
            if iSaldo is not None:
                await update.effective_message.reply_text(f"Tu saldo es de: {iSaldo} cuentas")
            else:
                await update.effective_message.reply_text(f"Tu saldo es de: 0 cuentas")
            return
        
async def get_saldo(update: Update) -> int:
    oData = update.callback_query
    if not oData:
        oData = update.message
    user_id = oData.from_user.id
    aUsers = await get_google_sheet_data(0)
    for oUser in aUsers:
        if oUser['ID'] == user_id:
            iSaldo = oUser['saldo']
            if iSaldo is not None:
                return iSaldo
            else:
                return 0
    return 0
        
async def gastar_saldo(update: Update) -> None:
    iSaldo = await get_saldo(update)
    if not iSaldo:
        await update.effective_message.reply_text(f"Tu saldo es de: 0 cuentas")
        return
    
    await update.effective_message.reply_text(f"Tu saldo es de: {iSaldo} cuentas \n ¿Cuantas quieres?")
    user_states[update.callback_query.from_user.id] = 'waiting_for_saldo'

# Ejecutar el JobQueue al iniciar la app
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_callback))
app.add_handler(MessageHandler(BaseFilter(), handle_message))

app.run_polling()