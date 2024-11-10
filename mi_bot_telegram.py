from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler
from oauth2client.service_account import ServiceAccountCredentials
from telegram.ext.filters import BaseFilter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta

import json
import os
import re
import gspread


TOKEN = '7627758916:AAErmy69sD3-NX6ITLmd1EY96Y_f2zSmllw'
admin_chat_id = 7525505749  # Reemplaza con el ID de tu chat
BD = 'BD BotTelegram'
user_states = {}


def get_google_client() :
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets", 'https://www.googleapis.com/auth/drive']
    google_credentials_str = os.getenv('GOOGLE_CREDENTIALS_JSON')
    print(f"GOOGLE_CREDENTIALS_JSON: {google_credentials_str}")  # Agrega esto para verificar
    if google_credentials_str is None:
        raise ValueError("La variable de entorno 'GOOGLE_CREDENTIALS_JSON' no está configurada correctamente.")
    
    google_credentials = json.loads(google_credentials_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_credentials, scope)
    #google_credentials = 'credentials.json'
    #creds = ServiceAccountCredentials.from_json_keyfile_name(google_credentials, scope)
    return gspread.authorize(creds)

async def get_google_sheet_data(sheet_id: int):
    googleClient = get_google_client()

    spreadsheet = googleClient.open('BD BotTelegram')
    sheet = spreadsheet.get_worksheet(sheet_id) 
    print(sheet)

    # Obtén todos los registros de la hoja
    aData = sheet.get_all_records()
    
    return aData

async def update_google_sheet(spreadsheet_name, worksheet_index, row, column, value):
    googleClient = get_google_client()
    sheet = googleClient.open(BD).get_worksheet(worksheet_index)
    sheet.update_cell(row, column, value)


#Funcion para validar si el usuario a mandado un correo
def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(email_regex, email) is not None

#Verifica que el correo sea válido y esté en la BD
async def handle_email_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    if not user_states.get(user_id) == 'waiting_for_email':
        return

    del user_states[user_id]
    
    if not await checkUser(update):
        return
    
    if not await verifyUserMaxReports(update, False):
        return
    
    user_message = update.message.text.strip()

    if not user_message or not is_valid_email(user_message):
        await update.message.reply_text("Por favor, introduce una dirección de correo válida.")
        return

    aData = await get_google_sheet_data(1)
    # Verifica si el correo está en la lista y pertenece al usuario que lo ha reportado de autorizados
    bValidUser = False
    bValidEmail = False
    bValidState = True
    iRow = 0
    for iIndex, oData in enumerate(aData):
        if oData['Correo'].lower() == user_message.lower() and oData['Estado'] == 'Error':
            bValidState = False
            break
        if oData['Correo'].lower() == user_message.lower() and oData['Usuario'] == user_id:
            bValidUser = True
            bValidEmail = True
            iRow = iIndex + 2
            break 
        if oData['Correo'].lower() == user_message.lower():
            bValidEmail = True
        

    if not bValidState:
        await update.message.reply_text(f'Esta cuenta ya ha sido reportada')
        return

    if bValidUser and bValidEmail:
        #await update.message.reply_text(f'Generando reemplazo...')
        await send_Netflix_replacement(update, iRow)

    if not bValidEmail:
        await update.message.reply_text(f"El correo '{user_message}' no se encuetra en la base de datos")
        await context.bot.send_message(chat_id=admin_chat_id, text=f'El usuario {user_id} ha escrito: {user_message} y no se encuetra en la base de datos')
        return

    if bValidEmail and not bValidUser:
        await update.message.reply_text(f"El correo '{user_message}' no se encuentra asociado a tu usuario")
        await context.bot.send_message(chat_id=admin_chat_id, text=f'El usuario {user_id} ha escrito: {user_message} y no se encuentra asociado a tu usuario')
        return

async def checkUser(update: Update) -> bool:
    user_id = update.message.from_user.id
    aData = await get_google_sheet_data(0)
    bFound = False
    for oData in aData:
        if oData['ID'] == user_id:
            bFound = True
            break
    return bFound

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
            print(f"entra 2")
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
        await update_google_sheet(BD, 2, row_to_delete, 1, "")  # Borrar ID Usuario
        await update_google_sheet(BD, 2, row_to_delete, 2, "")  # Borrar Fecha reporte
        print(f"Registro más antiguo del usuario {user_id} eliminado en la fila {row_to_delete}.")
    else:
        print("No se encontró el registro más antiguo para eliminar.")

async def send_Netflix_replacement(update, iRow) -> bool:
    aCuentas = await get_google_sheet_data(1)
    resultado, fila = next(
        ((obj, idx + 2) for idx, obj in enumerate(aCuentas) if obj['Usuario'] == '' and obj['Estado'] != 'Error'),
        (None, None)
    )

    if resultado:
        await update.message.reply_text(f"Reemplazo generado: \nCorreo: {resultado['Correo']}\nContraseña: {resultado['Contraseña']}")
        user_id = update.message.from_user.id
        #Rellenammos columna usuario de la cuenta que le hemos dado
        await update_google_sheet(BD, 1, fila, 3, user_id)

        #Rellenamos las columnas estado y ultimo usuario de la cuenta reportada
        await update_google_sheet(BD, 1, iRow, 4, 'Error')
        await update_google_sheet(BD, 1, iRow, 5, user_id)
        
        #await update.message.reply_text(f'Eliminando reporte mas antiguo...')
        await verifyUserMaxReports(update, True)

        #await update.message.reply_text(f'Añadiendo registro del reporte...')
        aReportes = await get_google_sheet_data(2)
        await update_google_sheet(BD, 2, len(aReportes) + 2, 1, user_id)
        fecha_hoy = datetime.now()
        fecha_formateada = fecha_hoy.strftime("%d/%m/%Y %H:%M:%S")
        await update_google_sheet(BD, 2, len(aReportes) + 2, 2, fecha_formateada)
        user_message = update.message.text.strip()
        await update_google_sheet(BD, 2, len(aReportes) + 2, 3, user_message)
        await update_google_sheet(BD, 2, len(aReportes) + 2, 4, resultado['Correo'])
        return True
    else:
        await update.message.reply_text("No hay reemplazos disponibles, prueba mas tarde.")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await checkUser(update):
        await update.message.reply_text('No tienes permisos para usar este bot')
        await add_log(update, 'KO', 'N/A', 'Usuario no autorizado intentado usar  el bot')
        return
    keyboard = [
        [
            InlineKeyboardButton("🔴 Reemplazo Netflix 🔴", callback_data="solicitar_correo"),
        ],
        [
            #InlineKeyboardButton("💰 Precios 💰", callback_data="ver_precios"),
            InlineKeyboardButton("📞 Contacto 📞", callback_data="ver_contacto")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f'Bienvenido al bot', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query.data == "solicitar_correo":
        await update.effective_message.reply_text("Introduce la dirección de correo electrónico que da error:")
        user_states[query.from_user.id] = 'waiting_for_email'

    #if query.data == "ver_precios":
    #    await update.effective_message.reply_text(f'Perfiles Extra de Netflix - 2€ al mes')

    if query.data == "ver_contacto":
        await update.effective_message.reply_text(f'Para contratar contactar con @confeti')

async def add_log(update: Update, sResult, sReplacement, sError) -> None:
    fecha_actual = datetime.now()
    user_id = update.message.from_user.id
    user_message = update.message.text.strip()
    aLogs = await get_google_sheet_data(3)
    iLastRow = len(aLogs) + 2

    await update_google_sheet(BD, 3, iLastRow, 1, fecha_actual)
    await update_google_sheet(BD, 3, iLastRow, 2, user_id)
    await update_google_sheet(BD, 3, iLastRow, 3, user_message)
    await update_google_sheet(BD, 3, iLastRow, 4, sResult)
    await update_google_sheet(BD, 3, iLastRow, 5, sReplacement)
    await update_google_sheet(BD, 3, iLastRow, 5, sError)

    
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_callback))
app.add_handler(MessageHandler(BaseFilter(), handle_email_message))

app.run_polling()