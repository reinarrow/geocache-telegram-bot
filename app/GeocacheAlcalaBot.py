import logging
import json
import psycopg2
import os

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

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
            cur.execute("CREATE TABLE chat_data (chat_id BIGINT PRIMARY KEY, current_step INT, current_question INT)")
            conn.commit()
    finally:
        cur.close()

init_db()

def get_config_data(step_id):
    """
    Get the data corresponding to the input step_id (comparing to the field id in the config file. The JSON is read every time to allow for configuration changes without having to restart the application)
    """
    config_path = 'config/history_metadata.json'
    try:
        with open(config_path, 'r') as history_file:
            history_data = json.load(history_file)
            # Find the data corresponding to the current step
            return next((step_data for step_data in history_data if step_data.get('id') == step_id), None)
    except FileNotFoundError:
        print(f"File not found: {config_path}")
    except Exception as e:
        print(f"An error occurred: {e}")

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
    print(chat_id)
    cur.execute("INSERT INTO chat_data (chat_id, current_step, current_question) VALUES (%s,%s,%s);", (chat_id, 0, 0))
    cur.close()
    send_next_step(0, update, context)

def get_current_chat_data(chat_id):
    cur = conn.cursor()
    cur.execute("SELECT current_step, current_question FROM chat_data WHERE chat_id=%s;",(chat_id,))
    current_chat_data = cur.fetchone()
    cur.close()
    return current_chat_data

def build_buttons_markup(buttons):
    buttons_markup = []

    # Generate list of markup for buttons
    markup = None
    for button in buttons:
        buttons_markup.append(InlineKeyboardButton(button['label'], callback_data=int(button['target_step'])))
    
    # Create full markup
    markup = InlineKeyboardMarkup([buttons_markup,])

    return markup

def button_tap(update: Update, context: CallbackContext) -> None:
    """
    This handler processes the inline buttons on the menu
    """
    # Find data from current chat to update the step
    chat_id = update.effective_chat.id
    next_step = int(update.callback_query.data)

    # Move to target step and reset current_question to 0
    cur = conn.cursor()
    cur.execute("UPDATE chat_data SET current_step=%s, current_question=%s WHERE chat_id=%s",(next_step, 0, chat_id))
    conn.commit()
    cur.close()

    # Close the query to end the client-side loading animation
    update.callback_query.answer()

    # Remove button
    context.bot.edit_message_reply_markup(chat_id=update.callback_query.message.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)

    # call the update function to send the next message
    send_next_step(next_step, update, context)

def send_next_step(step_id: int, update: Update, context: CallbackContext):    
    current_step_data = get_config_data(step_id)

    if current_step_data:
        # Update text        
        text = "<b>"+current_step_data.get('title')+"</b>"+"\n\n"+current_step_data.get('text')

        # Update buttons (if any)
        markup = build_buttons_markup(current_step_data.get('buttons'))

        # Send history markup (text + buttons)
        context.bot.send_message(
            update.effective_chat.id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )

        # Send first question if any
        first_question = (next((question for question in questions_config if question.get('id') == 0),'None')) if (questions_config := current_step_data.get('questions')) else None

        if first_question:
            send_question(update, context, first_question)

        # Send audio if any
        if audio_config := current_step_data.get('audio'):
            send_media(context, update.effective_chat.id, 'audio', 'audio/' + audio_config)            

        # Send image if any
        if image_config:= current_step_data.get('image'):
            send_media(context, update.effective_chat.id, 'photo', 'image/' + image_config)

    else:
        # No more steps, the history is done
        print("Step ", step_id, " not found")

def send_media (context, chat_id, type, path):
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
        print(f"File not found: {file}")
    except Exception as e:
        print(f"An error occurred: {e}")

def answer(update: Update, context: CallbackContext) -> None:
    """Process answer."""
    correct_answer = False

    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    current_step = None
    if current_chat_data:
        current_step = current_chat_data[0]

    # If current step is the introduction (0), first (1) or the last one, just give default message
    if current_step == 0:
        text = "Envía /start o pulsa el botón Start abajo para iniciar el bot"
    elif current_step == 1:
        text = "Pulsa el botón para empezar"
    elif current_step == 4:
        # TODO: Change this when the implementation of the end of the game logics is ready
        text = "El mundo te agradece tu labor evitando la catástrofe. Esperamos que lo hayas pasado bien."
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
                text = "Genial, se vé que sabes usar Google!"
                correct_answer = True
            else:
                text = "¿Estás seguro? Inténtalo de nuevo"
        else:
        # No current question exists. Send default message
            text = "Deja de charlar y manos a la obra. ¡Necesitamos tu ayuda para encontrar al Anthony!"

    update.message.reply_text(text)

    if correct_answer:
        # Check if there are pending questions
        next_question = None

        for question in questions:
            if question['id'] == current_question+1:
                next_question = question
        cur = conn.cursor()
        if next_question:           
            # Update current_question in DB            
            cur.execute("UPDATE chat_data SET current_question=%s WHERE chat_id=%s",(question['id'], chat_id))
            
            send_question(update, context, next_question)
        else:
            # No questions pending. Move to next step if any
            next_step = current_step+1
            cur.execute("UPDATE chat_data SET current_step=%s, current_question=%s WHERE chat_id=%s",(next_step, 0, chat_id))
            send_next_step(next_step, update, context)

        conn.commit()
        cur.close()

def send_question(update: Update, context: CallbackContext, question):

    # Send the question to the chat
    context.bot.send_message(
        update.effective_chat.id,
        question['question_text'],
        parse_mode=ParseMode.HTML,
        reply_markup=None
    )  
    
def main() -> None:
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    # Then, we register each handler and the conditions the update must meet to trigger it
    dispatcher = updater.dispatcher

    # Register commands
    dispatcher.add_handler(CommandHandler('start', start))    

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