import logging

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

logger = logging.getLogger(__name__)

BOT_TOKEN = "6236263968:AAEGJ7tA9buQD0fchSvouKv0xOc0oQKAgCA"

current_stage = "start"
# Store bot screaming status
#screaming = False

# Pre-assign menu text
WELCOME_MENU_TEXT = "<b>Hola, soy GeocacheBot</b>\n\nEncantado de conocerte. Mi propósito es guiarte a lo largo de esta aventura hasta entontrar el Geocaché final. Pulsa el siguiente botón para comenzar la historia. \n\nUna vez que lo pulses, el tiempo comenzará a contar, así que asegúrate de estar listo para emprender esta aventura antes de hacerlo."
HISTORY_MENU_TEXT = """<b>El Secreto del Relojero</b>
\n\nEn los años 80, la tecnología digital comenzaba a acaparar toda la atención. Hacía 10 años que los relojes digitales habían llegado para reemplazar al analógico y sus anticuadas manecillas. Esto estaba llevando a la ruina al joven Anthony Benbig. Un excelente relojero de procedencia inglesa asentado en Sevilla que veía como caían sus ventas y su fortuna se reducía drásticamente. La desesperación cambió su carácter y lo llevó a buscar nuevos proyectos. Se volvió taciturno y confinado en el taller que heredó tras la jubilación de su padre,  se topó con un descubrimiento que revolucionaría su escabroso futuro. Su padre, preocupado por su huraño hijo, entró al almacén y lo sorprendió fuera de sí con un deplorable aspecto y se percató de que estaba tramando algo turbio. Tras encontrarse con la negativa de parar ese peligroso proyecto, optó por lo sano y negó la entrada a las instalaciones. El padre no sabía sus verdaderas intenciones, pero no lo dudó tras la negativa a darle explicación alguna y su preocupante estado. Finalmente, denunció ante las autoridades a su hijo, quien sufrió una insoportable persecución que lo llevó a desaparecer. Pero no iba a desistir pués tenía algo muy importante entre manos. Esto terminó por romper la relación con su severo padre, que además de haberle hecho una infancia insoportable para convertirlo en el mejor relojero, ahora le truncaba su mayor proyecto.
\nEn su tiempo libre, Anthony había sido un entusiasta espeleólogo y esto le había llevado a conocer el subsuelo de Alcalá de Guadaíra como la palma de su mano. A lo largo de los años se le ha localizado por está zona. Sabemos que se instaló en alguna gruta y que continuó trabajando en su plan.
\nLa obra de Anthony es nada más y nada menos que una máquina del tiempo. Al principio, sus intenciones serían buenas, pero después de sufrir semejante acoso y de vivir apartado de la sociedad en las sombras, tenemos indicios de que sus pretensiones pueden poner en peligro la vida tal y como la conocemos. 
\nAquí empieza vuestro cometido. No tenéis de que preocuparos, pues vuestra actuación se realizará en la superficie. Un grave problema de los viajes en el tiempo es el cambio de la orografía. Donde hoy hay un cerro, en el pasado no lo había o donde hoy hay un puente, en el pasado había un acantilado. Esto significa que puede aparecer bajo tierra y morir sepultado o sobre 8 o 10 metros de altura y morir en la caida. Pero creemos que ha conseguido corregir esto mediante algún tipo de 'autonivelante". Por ello los portales están en la superficie.
\nDesconocemos la forma exacta como lo hace, pero suponemos que de algun modo emplaza cada viaje en el tiempo en lugares claves y cada salto deja un portal que tenéis que cerrar. Para ello debéis encontrarlo, recopilar algunos datos y por último, cerrarlo.Os llegará un listado de los puntos donde ustedes tendréis que actuar. Tenemos varios equipos como el vuestro en distintos emplazamientos, pues el tiempo apremia. 
\nAnthony está perfeccionando la máquina y creemos que su objetivo ahora es viajar a mediados de 1900 y atentar contra la vida de su padre. Esto crearía una paradoja temporal de consecuencias catastróficas."""
CACHE1_MENU_TEXT1 = """<b>Portal 1</b>
\n\nDesde aquí se puede divisar la ladera del cerro de la fortaleza que en su dia se llamó Qalat Yabir, por su origen almohade. La construcción de este castillo está datada en el siglo XI, aunque muy probablemente, este enclave ya contaba con alguna fortificación 2 siglos antes.
\nPara conseguir avanzar, debes responder a un par de preguntas. Veamos:
\n¿Qué rey le dió su configuración actual tras la reconquista en el siglo XIII? 
"""
CACHE1_MENU_TEXT2 ="""Genial! Ahora esta:
\n¿Cuántas torres lo flanquean?
"""

# Pre-assign button text
START_GAME_BUTTON_LABEL = "¡Comenzar la aventura!"
START_GAME_BUTTON_DATA = "start"
CONTINUE_BUTTON_LABEL = "Continuar"
CONTINUE_BUTTON_DATA = "continue"
CACHE1_BUTTON_LABEL = "Caché 1"
CACHE1_BUTTON_DATA = "cache1"
#BACK_BUTTON = "Back"
#TUTORIAL_BUTTON = "Tutorial"

# Build keyboards
WELCOME_MENU_MARKUP = InlineKeyboardMarkup([[
    InlineKeyboardButton(START_GAME_BUTTON_LABEL, callback_data=START_GAME_BUTTON_DATA)
]])
HISTORY_MENU_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton(CONTINUE_BUTTON_LABEL, callback_data=CONTINUE_BUTTON_DATA)],
    #[InlineKeyboardButton(TUTORIAL_BUTTON, url="https://core.telegram.org/bots/api")]
])
CACHE1_MENU_MARKUP = InlineKeyboardMarkup([
    #[InlineKeyboardButton(CACHE1_BUTTON_LABEL, callback_data=CACHE1_BUTTON_DATA)],
    #[InlineKeyboardButton(TUTORIAL_BUTTON, url="https://core.telegram.org/bots/api")]
])

RESPONSE_CACHE1_1 = "Fernando III"

def button_tap(update: Update, context: CallbackContext) -> None:
    """
    This handler processes the inline buttons on the menu
    """
    global current_stage

    data = update.callback_query.data
    text = ''
    markup = None

    if data == START_GAME_BUTTON_DATA:
        text = HISTORY_MENU_TEXT
        markup = HISTORY_MENU_MARKUP
    elif data == CONTINUE_BUTTON_DATA:
        text = CACHE1_MENU_TEXT1
        markup = CACHE1_MENU_MARKUP

        # Move to first stage
        current_stage = "cache1_1"
    #elif data == CACHE1_BUTTON_DATA:
    #    text = "Continuará..."
    #    markup = CACHE1_MENU_MARKUP

    # Close the query to end the client-side loading animation
    update.callback_query.answer()

    # Update message content with corresponding menu section
    update.callback_query.message.edit_text(
        text,
        ParseMode.HTML,
        reply_markup=markup
    )

def start(update: Update, context: CallbackContext):
    """
    This handler sends a menu with the inline buttons we pre-assigned above
    """

    context.bot.send_message(
        update.message.from_user.id,
        WELCOME_MENU_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=WELCOME_MENU_MARKUP
    )

def answer(update: Update, context: CallbackContext) -> None:
    """Process answer."""
    if current_stage == "start":
        text = "Pulsa el botón para empezar"
    elif current_stage == "cache1_1":
        if update.message.text == RESPONSE_CACHE1_1:
            text = "Genial, se vé que sabes usar Google!"
        else:
            text = "¿Estás seguro?"
    update.message.reply_text(text)

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