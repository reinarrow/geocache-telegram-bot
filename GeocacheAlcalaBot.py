import logging
import json
import psycopg2
import os

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

with open('history_metadata.json', 'r') as history_file:
    data = history_file.read()
history_data = json.loads(data)

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
            cur.execute("CREATE TABLE chat_data (chat_id INT PRIMARY KEY, current_step INT, current_question INT)")
            conn.commit()
    finally:
        cur.close()

init_db()

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
    current_step_data = None
    for step in history_data:
        if step['id'] == step_id:
            current_step_data = step
            break

    if current_step_data:
        # Update text        
        text = "<b>"+current_step_data['title']+"</b>"+"\n\n"+current_step_data['text']

        # Update buttons (if any)
        markup = build_buttons_markup(current_step_data['buttons'])

        # Send history markup (text + buttons)
        context.bot.send_message(
            update.effective_chat.id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup
        )

        # Send first question if any
        first_question = None
        if current_step_data['questions']:
            for question in current_step_data['questions']:
                if question['id'] == 0:
                    first_question = question
                    break

        if first_question:
            send_question(update, context, first_question)

    else:
        # No more steps, the history is done
        print("Step ", step_id, " not found")

def answer(update: Update, context: CallbackContext) -> None:
    """Process answer."""
    correct_answer = False

    chat_id = update.effective_chat.id
    current_chat_data = get_current_chat_data(chat_id)
    current_step = None
    if current_chat_data:
        current_step = current_chat_data[0]
    if current_chat_data == None or current_step == 0:
        text = "Envía /start o pulsa el botón Start abajo para iniciar el bot"

    else:
        current_question = current_chat_data[1]

        # Get current correct answer if any
        questions = None
        current_answer = None
        for step in history_data:
            if step['id'] == current_step:
                questions = step['questions']
                for question in questions:
                    if question['id'] == current_question:
                        current_answer = question['answer']

        
        if current_step == 1:
            text = "Pulsa el botón para empezar"
        elif current_answer:    
            if update.message and update.message.text.lower() == current_answer.lower():
                text = "Genial, se vé que sabes usar Google!"
                correct_answer = True
            else:
                text = "¿Estás seguro? Inténtalo de nuevo"
        elif current_step == 4:
            text = "El mundo te agradece tu labor evitando la catástrofe. Esperamos que lo hayas pasado bien."
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