import logging
import json
import psycopg2
import os
from datetime import datetime, timedelta, timezone

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from GeoCalculator import GeoCalculator

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

CONFIG_PATH = 'config/history_metadata.json'

# Radius of distance to accept to the next objective in kilometers during navigation (30 meters)
LOCATION_PRECISION = 0.01

HELP_QUERY_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

# Database connection handler
con = None

# Object containing the message update with the real-time location of the user
locations = {}

# Flag for name request in progress and temporary name store for verification
requesting_name = False
temp_name = None

# Flag for location sharing request in progress
requesting_location = False

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
            cur.execute("CREATE TABLE chat_data (chat_id BIGINT PRIMARY KEY, current_step INT, current_question INT, helps_used INT, start_time timestamp, total_time interval, username VARCHAR")
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

    request_name(update, context)

def request_name(update: Update, context: CallbackContext):
    """
    This function requests the user to specify their name
    """
    # Set flag to true to identify the next user message as a 
    global requesting_name
    requesting_name= True

    name_request = "Antes de empezar, ¿con qué nombre debo dirigirme a vosotros? Este nombre se utilizará al final para la tabla de clasificación por tiempos."
    context.bot.send_message(update.effective_chat.id, name_request)

def verify_name(name: str, update: Update, context: CallbackContext):
    """
    Verify if the introduced name is OK
    """

    global temp_name
    temp_name = name

    # Check if the name exists
    cur =  conn.cursor()
    cur.execute("SELECT username FROM chat_data WHERE username=%s;",(name,))
    same_name = cur.fetchone()
    
    if same_name:
        context.bot.send_message(update.effective_chat.id, "El nombre ya existe. Por favor, elige otro.")
        return

    buttons = []
    yes_button = {
        "id": 0,
        "label": "Sí",
        "data": 1
    }
    no_button = {
        "id": 1,
        "label": "No",
        "data": 0
    }

    # Add buttons to the list
    buttons.append(yes_button)
    buttons.append(no_button)

    # Build markup with buttons
    markup = build_buttons_markup(buttons)

    # Send history markup (text + buttons)
    context.bot.send_message(
        update.effective_chat.id,
        f'Tu nombre es {name}. ¿Es correcto?',
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    ) 

def register_user(update: Update, context: CallbackContext):
    """
    This function registers a new user after the name is specified, with the chat_id and name identification. 
    After that, it triggers the location request
    """
    global requesting_name
    requesting_name = False

    global temp_name
    cur =  conn.cursor()
    chat_id = update.effective_chat.id
    cur.execute("INSERT INTO chat_data (chat_id, current_step, current_question, helps_used, username) VALUES (%s,%s,%s,%s,%s);", 
                (chat_id, 0, 0, 0, temp_name))
    cur.close()

    request_location(update, context)
    # send_next_step(0, update, context)

def request_location(update: Update, context: CallbackContext):
    """
    This function requests the user to share their location with the bot and enable real-time
    """
    global requesting_location
    requesting_location = True

    current_chat_data = get_current_chat_data(update.effective_chat.id)
    username = current_chat_data[3]

    text = f"De acuerdo, {username}. Para poder ayudaros durante la búsqueda de las localizaciones, necesito acceso a vuestra ubicación en tiempo real. Para ello, pulsa en compartir, busca la opción de ubicación y marca la opción de compartir la ubicación en tiempo real (no solo la posición actual). Se te pedirá elegir el tiempo que quieres compartir la ubicación. Te recomiendo elegir 8 horas para no tener problemas. Ten en cuenta que puedes dejar de compartirla en cualquier momento si lo necesitas."
    context.bot.send_message(update.effective_chat.id, text)    

def get_current_chat_data(chat_id):
    cur = conn.cursor()
    cur.execute("SELECT current_step, current_question, helps_used, username FROM chat_data WHERE chat_id=%s;",(chat_id,))
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

    chat_id = update.effective_chat.id
    # Close the query to end the client-side loading animation
    if callback_query := update.callback_query:
        callback_query.answer()

        # Remove button
        context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=callback_query.message.message_id, reply_markup=None)

    # Find data from current chat to update the step    
    if update.callback_query and update.callback_query.data:
        next_step = int(update.callback_query.data) 
    else:
        logging.error('Error while retrieving data from the button.')
        return
                
    # Check if the user is creating the name
    global requesting_name
    if requesting_name:
        if next_step == 0:
            # User clicked NO
            context.bot.send_message(chat_id, "De acuerdo, introduce el nuevo nombre")
        else:
            # User clicked YES
            register_user(update, context)
        return

    current_chat_data = get_current_chat_data(chat_id)
    current_step = current_chat_data[0]
    current_step_data = get_config_data(current_step)            

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
    if len(questions) > 0 and step_id != get_last_step() - 1:
        # Do not send the button if we are moving to the last step as there is no jump to the past
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

    # Check if the answer belongs to the name registration
    global requesting_name
    if requesting_name:
        verify_name(update.message.text, update, context)
        return

    if update.message and update.message.text.lower() == "skip":
        on_location_found(update, context)
        return
    
    # This is triggered with the user has already shared the location and clicks on the radar button afterwards
    if update.message and "radar portatemporal" in update.message.text.lower():
        execute_radar(update, context)
        return
    
    correct_answer = False

    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    current_step = None
    if current_chat_data:
        current_step = current_chat_data[0]

    # If current step is the introduction (0), just give default message
    if current_step == 0 or current_step == None:
        text = "Envía /start o pulsa el botón Inicio para comenzar"        
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
                text = "¡Correcto!"
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
        elif current_step == get_last_step() - 1:
            # Move to last step without navigation
            next_step = current_step + 1
            cur.execute("UPDATE chat_data SET current_step=%s, current_question=%s WHERE chat_id=%s",(next_step, 0, chat_id))
            send_next_step(next_step, update, context)
        else:
            start_navigation(update, context)       
        conn.commit()
        cur.close()

def start_navigation(update: Update, context: CallbackContext):
    # Send message about portal closed and navigation start if there is coordinates
    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    if current_chat_data:
        current_step_data = get_config_data(current_chat_data[0])

    if image_config:= current_step_data.get('image'):
        send_media(context, update.effective_chat.id, 'photo', 'image/' + image_config)

    # If there is a navigation phase (next_coordinates is not null), include the button to send the location
    if current_step_data.get('next_coordinates'):
        # Make radar button visible for navigation phase
        keyboard = [[KeyboardButton(text="Radar portatemporal 🧭", request_location=False)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        context.bot.send_message(
            update.effective_chat.id,
            f'Es hora de navegar al siguiente objetivo. Si no veis el radar, pulsad el botón con cuatro cuadrados junto al campo de texto del chat. Si la posición del radar no se actualiza, abrid la ubicación que se está compartiendo pulsando en \"En tiempo real\" para forzar a que se actualice y luego usar el radar.',
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
            'Aquí tenéis el botón de ayuda a la navegación. ¡Recordad no abusar de él!',
            reply_markup=markup)   

def send_question(update: Update, context: CallbackContext, question):
    # Send the question to the chat
    context.bot.send_message(
        update.effective_chat.id,
        question['question_text'],
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )  
def location(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id

    # If location request is in progress
    global requesting_location
    if requesting_location:
        logging.info(f'Requesting location is enabled')
        if update.message and update.message.location and update.message.location.live_period:
            requesting_location = False

            # Live location correctly shared. Persist current location and start the adventure
            context.bot.send_message(chat_id, "Genial, has completado la configuración. ¡Comencemos!")
            send_next_step(0, update, context)

        elif not update.edited_message:
            # Only react to manually sent location
            context.bot.send_message(chat_id, "Necesito que compartas la ubicación EN TIEMPO REAL, no la actual. Si no ves esta opción, intenta deslizar hacia abajo.")
        return
    
    # Automatic location send without the initial request. Process it and update stored value.
    logging.info(f'edited message: {update.edited_message}')
    if message := update.edited_message:
        global locations
        locations[chat_id] = message 
        logging.info(f'Stored new location: {locations}')
    else:
        logging.warning('Received a manual location outside the request period. Ignoring...')

def execute_radar(update: Update, context: CallbackContext):
    """
    Execute the radar, by using the latest available location from the user (shared in real time with the bot).
    Check for proximity to the next target.
    """
    global locations
    chat_id = update.effective_chat.id
    logging.info(f'Chat ID: {chat_id}')
    
    last_location = locations.get(chat_id)
    # Check if there is location stored and if the time since the last location was received to detect stopped auto location
    if not last_location or (datetime.now(timezone.utc) - last_location.edit_date).total_seconds() > 40:
        logging.error(f'No location stored for user {chat_id} or stopped real time location')
        context.bot.send_message(chat_id, "Hay problemas con tu localización en tiempo real. Por favor compártela de nuevo. Si la acabas de compartir, espera 30 segundos para que se estabilice y vuelve a intentarlo.")
        return

    user_coords = (last_location.location.latitude, last_location.location.longitude)
    
    # Find data from current chat to get the target coordinates
    current_chat_data = get_current_chat_data(update.effective_chat.id)
    current_step_data = get_config_data(current_chat_data[0])

    if not current_step_data:
        logging.error(f'No data for current step for user {chat_id}')
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
    
    next_step = current_step + 1

    if next_step == get_last_step() - 1:
        send_next_step(next_step, update, context)
        return
    if not current_step_data:
        return
    
    # Send a button for the user to confirm that they want to move to next point
    button = [        
        {
            "id": 1,
            "label": "Estoy listo",
            "data": next_step
        }
    ]    

    text = f'Estáis demasiado cerca del portal, es hora de que alguno de ustedes tome el mando y demuestre de que pasta está hecho. Coge el radar y continúa solo hasta el portal mientras vas narrando lo que ocurre a tus compañeros.'
    markup = build_buttons_markup(button)
    
    # Send history markup (text + buttons)
    context.bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )  

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