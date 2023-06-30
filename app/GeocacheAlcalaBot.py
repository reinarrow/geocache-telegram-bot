import logging
import json
import psycopg2
import os
from datetime import datetime, timedelta

from telegram import Update, ForceReply,ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from GeoCalculator import GeoCalculator

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

CONFIG_PATH = 'config/history_metadata.json'

# Radius of distance to accept to the next objective in kilometers during navigation (30 meters)
LOCATION_PRECISION = 0.03

HELP_QUERY_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

con = None
cur = None

def init_db():
    db_host = os.environ.get('POSTGRES_HOST')
    db_port = os.environ.get('POSTGRES_PORT')
    db_name = os.environ.get('POSTGRES_DB')
    db_user = os.environ.get('POSTGRES_USER')
    db_password = os.environ.get('POSTGRES_PASSWORD')

    global conn
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_password
    )
    cur =  conn.cursor()

    # Check if the table name already exists and create it otherwise
    try:
        cur.execute("SELECT EXISTS(SELECT * FROM information_schema.tables WHERE table_name='chat_data')")
        table_exists = cur.fetchone()[0]

        if not table_exists:
            cur.execute("CREATE TABLE chat_data (chat_id BIGINT PRIMARY KEY, current_step INT, current_question INT, helps_used INT, start_time timestamp, total_time interval)")
            conn.commit()
    finally:
        cur.close()

init_db()

def get_config_data(step_id):
    """
    Get the data corresponding to the input step_id (comparing to the field id in the config file. The JSON is read every time to allow for configuration changes without having to restart the application)
    """    
    try:
        with open(CONFIG_PATH, 'r') as history_file:
            history_data = json.load(history_file)
            # Find the data corresponding to the current step
            return next((step_data for step_data in history_data if step_data.get('id') == step_id), None)
    except FileNotFoundError:
        logging.error(f"File not found: {CONFIG_PATH}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

def get_last_step():
    """
    Get the maximum step in the history config file
    """ 
    try:
        with open(CONFIG_PATH, 'r') as history_file:
            history_data = json.load(history_file)
            return max(data.get('id') for data in history_data)
    except FileNotFoundError:
        logging.error(f"File not found: {CONFIG_PATH}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

def start(update: Update, context: CallbackContext):
    """
    This handler sends a menu with the text and inline buttons of the welcome message
    """
    chat_id = update.effective_chat.id

    # Check that there is not existing data for current user
    cur =  conn.cursor()
    cur.execute("SELECT current_step, current_question FROM chat_data WHERE chat_id=%s;",(chat_id,))
    current_chat_data = cur.fetchone()
    
    if current_chat_data:
        # If the user already existed, resend the initial instructions. Might be useful if they did not start the adventure but the chat got lost. Otherwise, they will not know how to start
        if(current_chat_data[0] == 0):
            send_next_step(0, update, context)
        return
    cur.execute("INSERT INTO chat_data (chat_id, current_step, current_question, helps_used) VALUES (%s,%s,%s,%s);", (chat_id, 0, 0, 0))
    cur.close()
    send_next_step(0, update, context)

def get_current_chat_data(chat_id):
    cur = conn.cursor()
    cur.execute("SELECT current_step, current_question, helps_used FROM chat_data WHERE chat_id=%s;",(chat_id,))
    current_chat_data = cur.fetchone()
    cur.close()
    return current_chat_data

def build_buttons_markup(buttons):
    buttons_markup = []

    # Generate list of markup for buttons
    for button in buttons:
        buttons_markup.append(InlineKeyboardButton(button.get('label'), callback_data=int(button.get('data'))))
    
    # Create full markup
    markup = InlineKeyboardMarkup([buttons_markup,])

    return markup

def button_tap(update: Update, context: CallbackContext) -> None:
    """
    This handler processes the inline buttons on the menu
    """
    # Find data from current chat to update the step
    chat_id = update.effective_chat.id
    if update.callback_query and update.callback_query.data:
        next_step = int(update.callback_query.data) 
    else:
        logging.error('Error while retrieving data from the button.')
        return

    current_chat_data = get_current_chat_data(chat_id)
    current_step = current_chat_data[0]
    current_step_data = get_config_data(current_step)            

    # Close the query to end the client-side loading animation
    if callback_query := update.callback_query:
        callback_query.answer()

        # Remove button
        context.bot.edit_message_reply_markup(chat_id=callback_query.message.chat_id, message_id=callback_query.message.message_id, reply_markup=None)
        
    # Id of the Help button is -1
    if next_step == -1:
        # Get link to coordinates for current step
        next_coordinates = current_step_data.get('next_coordinates')
        
        # Send help message
        if next_coordinates:
            # Construct help link to the next coordinates
            help_link = HELP_QUERY_URL.format(lat=next_coordinates[0], lon=next_coordinates[1])

            # Send history markup (text + buttons)
            context.bot.send_message(update.effective_chat.id, f'De acuerdo, aquí tienes las coordenadas: {help_link}')

            # Add one help to total cout            
            prev_helps_used = current_chat_data[2]

            cur = conn.cursor()
            cur.execute("UPDATE chat_data SET helps_used=%s WHERE chat_id=%s",(prev_helps_used+1, chat_id))
            conn.commit()
            cur.close()
        else: 
            context.bot.send_message(update.effective_chat.id, "Lo siento, no hay ayuda disponible en este momento.")   
    elif next_step == -2:    
        # Button to move from the time travel narration to questions       
        questions = current_step_data.get('questions')
        for question in questions:
            if question['id'] == 0:
                send_question(update, context, question)
                break

        # If the code gets here, there are not questions in this step.
        logging.warning('No question was found for current step.')  
    else:
        # call the update function to send the next message
        send_next_step(next_step, update, context)

def send_next_step(step_id, update: Update, context: CallbackContext):    
    chat_id = update.effective_chat.id
    current_step_data = get_config_data(step_id)

    # Move to target step and reset current_question to 0        
    cur = conn.cursor()
    cur.execute("UPDATE chat_data SET current_step=%s, current_question=%s WHERE chat_id=%s",(step_id, 0, chat_id))

    buttons = []
    if step_id == 0:
        # Reset helps, start_time and total_time
        cur.execute("UPDATE chat_data SET helps_used=%s, start_time=%s, total_time=%s WHERE chat_id=%s",(0, None, None, chat_id))  

        start_button = {
            "id": 1,
            "label": "¡Comenzar la aventura!",
            "data": 1
        }   
        buttons.append(start_button)

    elif step_id == 1:
        # Player just started. Store init time
        now = datetime.now()
        cur.execute("UPDATE chat_data SET start_time=%s WHERE chat_id=%s",(now, chat_id))

        reset_button = {
            "id": 1,
            "label": "Reiniciar",
            "data": 0
        }
        buttons.append(reset_button)

    elif step_id == get_last_step():
        end_time = datetime.now()
        # Get the user start time to calculate elapsed
        cur.execute("SELECT start_time, helps_used FROM chat_data WHERE chat_id=%s;",(chat_id,))
        data = cur.fetchone()
        # Final time before punishment for using helps
        elapsed = end_time - data[0]
        # Total time adding 5 minutes for each used help
        total_time = elapsed + timedelta(minutes = 5*data[1])

        # Write final score to database for the highscore future functionality
        cur.execute("UPDATE chat_data SET total_time=%s WHERE chat_id=%s",(total_time, chat_id))

        # Calculate the total number of seconds
        elapsed_seconds = int(elapsed.total_seconds())
        total_seconds = int(total_time.total_seconds())

        final_report =f"Tu tiempo total ha sido de {elapsed_seconds // 3600} horas y {(elapsed_seconds % 3600) // 60} minutos y has usado {data[1]} ayudas. Por lo tanto, tu tiempo final es de {total_seconds // 3600} horas y {(total_seconds % 3600) // 60} minutos (5 min más por cada ayuda)."

        send_media(context, chat_id, 'photo', 'image/gracias.jpg')
        context.bot.send_message(update.effective_chat.id, final_report)

    conn.commit()
    cur.close()    

    if not current_step_data:
        # No more steps, the history is done
        logging.info(f"Step {step_id} not found")
        return
    
    # Update text        
    text = "<b>"+current_step_data.get('title')+"</b>"+"\n\n"+current_step_data.get('text')

    # If there are questions, add a button to move to the questions after the portal narration
    questions = current_step_data.get('questions')
    if len(questions) > 0:
        logging.info("Adding button for transition to questions")
        question_transition_button = {
                "id": len(buttons)+1,
                "label": "Regresar al presente",
                "data": -2
            }

        # Add an element to the list
        buttons.append(question_transition_button)

    # Update buttons (if any)
    markup = build_buttons_markup(buttons)

    # Send history markup (text + buttons)
    context.bot.send_message(
        update.effective_chat.id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )        

    # Send audio if any
    if audio_config := current_step_data.get('audio'):
        send_media(context, update.effective_chat.id, 'audio', 'audio/' + audio_config)     
    
    # In step 1, navigation should start right away, without having to answer questions
    if step_id == 1:
        start_navigation(update, context)   

def send_media(context, chat_id, type, path):
    """
    Helper to send a media file to the chat, resilient in case the file does not exist

    :param context: The context of the telegram bot
    :param chat_id: Id of the chat to send the file to
    :param type: Type of file. Can be 'audio' or 'photo'
    :param path: Relative path to the file to be sent
    """
    try:
        with open(path, "rb") as file:
                if(type == 'photo'):
                    context.bot.send_photo(
                        chat_id = chat_id, 
                        photo = file
                    )
                elif(type == 'audio'):
                    context.bot.send_audio(
                        chat_id = chat_id, 
                        audio = file
                    )
    except FileNotFoundError:
        logging.error(f"File not found: {file}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")

def answer(update: Update, context: CallbackContext) -> None:
    """Process answer."""
    ## TODO: Remove this for debugging
    if update.message and update.message.text.lower() == "skip":
        on_location_found(update, context)
        return
    correct_answer = False

    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    current_step = None
    if current_chat_data:
        current_step = current_chat_data[0]

    # If current step is the introduction (0), just give default message
    if current_step == 0:
        text = "Envía /start o pulsa el botón Start abajo para iniciar el bot"
    else:
        # Intermediate step, check if there is an ongoing question and get the answer from history metadata        
        current_question = current_chat_data[1]

        # Get current correct answer if any
        current_answer = None
        current_step_data = get_config_data(current_step)
        questions = current_step_data.get('questions')
        for question in questions:
            if question['id'] == current_question:
                current_answer = question.get('answer')
                break 
        if current_answer:    
            if update.message and update.message.text.lower() == current_answer.lower():
                text = "Correcto"
                correct_answer = True
            else:
                text = "¿Estás seguro? Inténtalo de nuevo"
        else:
        # No current question exists. Send default message
            text = "Deja de charlar y manos a la obra. ¡Necesitamos tu ayuda para encontrar a Anthony!"

    update.message.reply_text(text)

    if correct_answer:
        # Check if there are pending questions
        next_question = None

        for question in questions:
            if question['id'] == current_question+1:
                next_question = question
                break
        cur = conn.cursor()
        # Update current_question in DB       
        cur.execute("UPDATE chat_data SET current_question=%s WHERE chat_id=%s",(current_question+1, chat_id))
        if next_question:                                        
            send_question(update, context, next_question)
        else:
            start_navigation(update, context)       
        conn.commit()
        cur.close()

def start_navigation(update: Update, context: CallbackContext):
    # Send message about portal closed and navigation start if there is coordinates
    # Send image if any

    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    if current_chat_data:
        current_step_data = get_config_data(current_chat_data[0])

    if image_config:= current_step_data.get('image'):
        send_media(context, update.effective_chat.id, 'photo', 'image/' + image_config)

    # If there is a navigation phase (next_coordinates is not null), include the button to send the location
    if current_step_data.get('next_coordinates'):
        keyboard = [[KeyboardButton(text="Radar", request_location=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        context.bot.send_message(
            update.effective_chat.id,
            f'Es hora de navegar al siguiente objetivo. Si no veis el radar, pulsad el botón con cuatro cuadrados junto al campo de texto del chat.',
            reply_markup=reply_markup)  

        # Send help button
        button = [        
            {
                "id": 1,
                "label": "Ayuda",
                "data": -1
            }
        ]   
        markup = build_buttons_markup(button)

        context.bot.send_message(
            update.effective_chat.id,
            'Aquí tenéis el botón de ayuda en caso de que os perdáis. ¡Recordad no abusar de él!',
            reply_markup=markup)   

def send_question(update: Update, context: CallbackContext, question):
    # Send the question to the chat
    context.bot.send_message(
        update.effective_chat.id,
        question['question_text'],
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )  

def request_location(update: Update, context: CallbackContext) -> None:   
    keyboard = [[KeyboardButton(text="Send Your Location", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    update.message.reply_text(f'Text',
                              reply_markup=reply_markup)

def location(update: Update, context: CallbackContext):
    current_pos = update.message.location
    logging.info(current_pos)
    
    user_coords = (current_pos.latitude, current_pos.longitude)
    
    # Find data from current chat to get the target coordinates
    current_chat_data = get_current_chat_data(update.effective_chat.id)
    current_step_data = get_config_data(current_chat_data[0])

    if not current_step_data:
        return
        
    next_coordinates = current_step_data.get('next_coordinates')
    if not next_coordinates:
        update.message.reply_text(f'No hay ningún objetivo activo.',
                                reply_markup=None)
        return            

    distance = GeoCalculator.calculate_distance(user_coords, tuple(next_coordinates))
    logging.info(f"Distance: {distance} kilometers")
    if distance <= LOCATION_PRECISION:
        on_location_found(update, context)
    else:
        bearing = GeoCalculator.calculate_compass_bearing(user_coords, next_coordinates)
        bearing_name = GeoCalculator.convert_bearing_to_cardinal(bearing)
        update.message.reply_text(f'El objetivo se encuentra a {round(distance*1000)} metros en dirección {bearing_name} ({bearing}° respecto del Norte).')

def on_location_found(update: Update, context: CallbackContext):
        # Find data from current chat to get the target coordinates
    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    current_step = current_chat_data[0]
    current_step_data = get_config_data(current_step)

    # Remove the navigation button
    text = f'Estáis demasiado cerca del portal, es hora de que alguno de ustedes tome el mando y demuestre de que pasta está hecho. Coge el radar y continúa solo hasta el portal mientras vas narrando lo que ocurre a tus compañeros.'
    if current_step == 9:
        text = f'Habéis encontrado la entrada de la cueva. Si tenéis el valor necesario, es hora de entrar y descubrir los planes secretos de Anthony.'        
    update.message.reply_text(text, reply_markup=None)
    

    if not current_step_data:
        return
    
    next_step = current_step+1

    # Send a button for the user to confirm that they want to move to next point
    button = [        
        {
            "id": 1,
            "label": "Estoy listo",
            "data": next_step
        }
    ]

    markup = build_buttons_markup(button)

    # Send history markup (text + buttons)
    context.bot.send_message(
        chat_id,
        'Pulsa el botón cuando estés listo',
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )  

    # Move to next step if any
    cur.execute("UPDATE chat_data SET current_step=%s, current_question=%s WHERE chat_id=%s",(next_step, 0, chat_id))
    send_next_step(next_step, update, context)

def main() -> None:
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    # Then, we register each handler and the conditions the update must meet to trigger it
    dispatcher = updater.dispatcher

    # Register commands
    dispatcher.add_handler(CommandHandler('start', start))    

    # Register handler for location sharing
    dispatcher.add_handler(MessageHandler(Filters.location, location))

    # Register handler for inline buttons
    dispatcher.add_handler(CallbackQueryHandler(button_tap))

    # on non command i.e message - echo the message on Telegram
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, answer))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C
    updater.idle()


if __name__ == '__main__':
    main()