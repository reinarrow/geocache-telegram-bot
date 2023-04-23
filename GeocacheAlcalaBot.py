import logging
import json

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

logger = logging.getLogger(__name__)

BOT_TOKEN = "6236263968:AAEGJ7tA9buQD0fchSvouKv0xOc0oQKAgCA"

with open('history_metadata.json', 'r') as history_file:
    data = history_file.read()
history_data = json.loads(data)

user_data = []

def start(update: Update, context: CallbackContext):
    """
    This handler sends a menu with the text and inline buttons of the welcome message
    """
    chat_id = update.effective_chat.id

    # Check that there is not existing data for current user
    for obj in user_data:
        if obj.get('chat_id') == chat_id:
            update.message.reply_text('Ya has iniciado el juego.')
            return

    # Initiate new user_data instance with the chat_id, current step, current expected answers and pending questions 
    user_data.append(
    {
        'chat_id': chat_id,
        'current_step': 0,
        'current_answer': None,
        'pending_questions': []
    })

    send_next_step(update, context)

def get_current_chat_data(update: Update):
    chat_id = update.effective_chat.id
    current_chat_data = None
    for user in user_data:
        if user['chat_id'] == chat_id:
            current_chat_data = user
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
    current_chat_data = None
    for user in user_data:
        if user['chat_id'] == chat_id:
            current_chat_data = user

    # Move to target step and call the update function to send the updated message
    current_chat_data['current_step'] = int(update.callback_query.data)
    # Close the query to end the client-side loading animation
    update.callback_query.answer()

    # Remove button
    context.bot.edit_message_reply_markup(chat_id=update.callback_query.message.chat_id, message_id=update.callback_query.message.message_id, reply_markup=None)

    send_next_step(update, context)

def send_next_step(update: Update, context: CallbackContext):    
    # Look for the current step data

    # Find data from current chat to update the step
    chat_id = update.effective_chat.id
    current_chat_data = None
    for user in user_data:
        if user['chat_id'] == chat_id:
            current_chat_data = user

    current_chat_data['current_answer'] = None
    current_step_data = None
    for step in history_data:
        if step['id'] == current_chat_data['current_step']:
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
        current_chat_data['pending_questions'] = current_step_data['questions']
        first_question = None
        if current_chat_data['pending_questions']:
            for question in current_chat_data['pending_questions']:
                if question['id'] == 0:
                    first_question = question
                    break

        if first_question:
            current_chat_data['current_answer'] = first_question['answer']
            current_chat_data['pending_questions'].remove(first_question)
            send_question(update, context, first_question)
    else:
        # No more steps, the history is done
        print("Step ", current_chat_data['current_step'], " not found")

def answer(update: Update, context: CallbackContext) -> None:
    """Process answer."""
    chat_id = update.effective_chat.id
    current_chat_data = None
    for user in user_data:
        if user['chat_id'] == chat_id:
            current_chat_data = user    

    correct_answer = False
    if current_chat_data == None or current_chat_data['current_step'] == 0:
        text = "Envía /start o pulsa el botón Start abajo para iniciar el bot"
    elif current_chat_data['current_step'] == 1:
        text = "Pulsa el botón para empezar"
    elif current_chat_data['current_answer']:    
        if update.message and update.message.text.lower() == current_chat_data['current_answer'].lower():
            text = "Genial, se vé que sabes usar Google!"
            correct_answer = True
        else:
            text = "¿Estás seguro? Inténtalo de nuevo"
    elif current_chat_data['current_step'] == 4:
        text = "El mundo te agradece tu labor evitando la catástrofe. Esperamos que lo hayas pasado bien."
    else:
        # No current question exists. Send default message
        text = "Deja de charlar y manos a la obra. ¡Necesitamos tu ayuda para encontrar al Anthony!"
    update.message.reply_text(text)

    if correct_answer:
        # Check if there are pending questions
        if len(current_chat_data['pending_questions']) > 0:
            # Find the question with the lowest ID
            lowest_id = current_chat_data['pending_questions'][0]['id']
            next_question = current_chat_data['pending_questions'][0]
            for question in current_chat_data['pending_questions']:
                if question['id'] < lowest_id:
                    lowest_id = question['id']
                    next_question = question
            
            current_chat_data['current_answer'] = next_question['answer']
            current_chat_data['pending_questions'].remove(next_question)
            send_question(update, context, next_question)

        else:
            # No questions pending. Move to next step if any
            current_chat_data['current_step'] = current_chat_data['current_step']+1
            send_next_step(update, context)

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