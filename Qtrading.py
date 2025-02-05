import yfinance as yf
import pandas as pd
import warnings
from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

# Suppress all warnings
warnings.filterwarnings('ignore')
pd.options.mode.chained_assignment = None

# Bot settings
TELEGRAM_BOT_TOKEN = '@'
TELEGRAM_CHAT_ID = -@

# Store active signals with persistence
active_signals = {}
last_check_time = None

FOREX_PAIRS = [
    'EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X', 'USDCAD=X',
    'USDCHF=X', 'NZDUSD=X', 'EURGBP=X', 'EURJPY=X', 'GBPJPY=X',
    'AUDJPY=X', 'EURCHF=X', 'GBPCHF=X', 'CADJPY=X', 'CHFJPY=X'
]

def calculate_sma(data, window=21):
    return data.rolling(window=window).mean()

def calculate_rsi(data, periods=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_market_open():
    now = pd.Timestamp.now().tz_localize('UTC')
    # Check if it's weekend
    if now.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return False, "Market is closed (Weekend)"
    return True, "Market is open"

def get_forex_data(pair):
    try:
        is_open, status = is_market_open()
        if not is_open:
            return None
        data = yf.download(pair, period='1d', interval='1m', progress=False)
        return data
    except Exception as e:
        return None

def send_signal(context: CallbackContext):
    print("Checking signals...")
    current_time = pd.Timestamp.now()
    
    # First, check and update all existing signals
    signals_to_remove = []
    for pair_name, signal_info in active_signals.items():
        try:
            time_diff = (current_time - signal_info['time']).total_seconds()
            if time_diff >= 180:  # 3 minutes
                data = get_forex_data(pair_name + "=X")
                if data is not None and not data.empty:
                    last_close = float(data['Close'].iloc[-1])
                    signal_type = signal_info['type']
                    entry_price = signal_info['price']
                    msg_id = signal_info['message_id']
                    
                    # Calculate pip difference
                    price_diff = (last_close - entry_price) * 10000
                    
                    if signal_type == 'BUY':
                        result = "Won 🎯" if price_diff > 0 else "Lost 📉"
                        pips = abs(price_diff)
                    else:  # SELL
                        result = "Won 🎯" if price_diff < 0 else "Lost 📉"
                        pips = abs(price_diff)
                    
                    update_text = f"{signal_info['message']}\nClose Price: {last_close:.4f}\nPips: {pips:.1f}\nResult: {result}"
                    context.bot.edit_message_text(
                        chat_id=TELEGRAM_CHAT_ID,
                        message_id=msg_id,
                        text=update_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    signals_to_remove.append(pair_name)
                    print(f"Updated signal for {pair_name} with result: {result}")
        except Exception as e:
            print(f"Error updating signal for {pair_name}: {str(e)}")
            signals_to_remove.append(pair_name)
    
    # Remove processed signals
    for pair_name in signals_to_remove:
        active_signals.pop(pair_name, None)
    
    # Now check for new signals
    for pair in FOREX_PAIRS:
        try:
            data = get_forex_data(pair)
            if data is None or data.empty or len(data) < 22:
                continue

            data['SMA21'] = calculate_sma(data['Close'])
            data['RSI'] = calculate_rsi(data)

            # Get the last two valid (non-NaN) values
            last_close = data['Close'].iloc[-1]
            prev_close = data['Close'].iloc[-2]
            last_sma = data['SMA21'].dropna().iloc[-1]
            prev_sma = data['SMA21'].dropna().iloc[-2]
            last_rsi = data['RSI'].dropna().iloc[-1]
            prev_rsi = data['RSI'].dropna().iloc[-2]

            pair_name = pair.replace('=X', '')

            # Check Buy conditions
            price_below_sma = float(last_close) < float(last_sma)
            price_was_above_sma = float(prev_close) > float(prev_sma)
            rsi_below_50 = float(last_rsi) <= 50
            rsi_was_above_50 = float(prev_rsi) > 50

            # Check Sell conditions
            price_above_sma = float(last_close) > float(last_sma)
            price_was_below_sma = float(prev_close) < float(prev_sma)
            rsi_above_50 = float(last_rsi) >= 50
            rsi_was_below_50 = float(prev_rsi) < 50

            signal_status = "No Signal"
            if price_above_sma and price_was_below_sma and rsi_above_50 and rsi_was_below_50:
                signal_status = "SELL SIGNAL"
            elif price_below_sma and price_was_above_sma and rsi_below_50 and rsi_was_above_50:
                signal_status = "BUY SIGNAL"

            print(f"{pair_name:<8} → {signal_status}")

            current_time = pd.Timestamp.now()
            
            # Check and update previous signals
            if pair_name in active_signals:
                time_diff = (current_time - active_signals[pair_name]['time']).total_seconds()
                # Update signals between 180-240 seconds to ensure we don't miss the update
                if 180 <= time_diff <= 240:  # 3-4 minutes window
                    signal_type = active_signals[pair_name]['type']
                    entry_price = active_signals[pair_name]['price']
                    msg_id = active_signals[pair_name]['message_id']
                    
                    # Calculate pip difference (multiply by 10000 for standard forex pairs)
                    price_diff = (float(last_close) - entry_price) * 10000
                    
                    if signal_type == 'BUY':
                        result = "Won 🎯" if price_diff > 0 else "Lost 📉"
                        pips = abs(price_diff)
                    else:  # SELL
                        result = "Won 🎯" if price_diff < 0 else "Lost 📉"
                        pips = abs(price_diff)
                    
                    current_price = float(last_close)
                    
                    update_text = f"{active_signals[pair_name]['message']}\nClose Price: {current_price:.4f}\nPips: {pips:.1f}\nResult: {result}"
                    context.bot.edit_message_text(chat_id=TELEGRAM_CHAT_ID,
                                               message_id=msg_id,
                                               text=update_text,
                                               parse_mode=ParseMode.MARKDOWN)
                    del active_signals[pair_name]

            # Send new signals
            if price_above_sma and price_was_below_sma and rsi_above_50 and rsi_was_below_50:
                signal = f"🔴 *{pair_name}* Sell Signal\nPrice: {float(last_close):.4f}\nTime 3 min"
                message = context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=signal, parse_mode=ParseMode.MARKDOWN)
                active_signals[pair_name] = {
                    'type': 'SELL',
                    'price': float(last_close),
                    'time': current_time,
                    'message_id': message.message_id,
                    'message': signal
                }
            elif price_below_sma and price_was_above_sma and rsi_below_50 and rsi_was_above_50:
                signal = f"🟢 *{pair_name}* Buy Signal\nPrice: {float(last_close):.4f}\nTime 3 min"
                message = context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=signal, parse_mode=ParseMode.MARKDOWN)
                active_signals[pair_name] = {
                    'type': 'BUY',
                    'price': float(last_close),
                    'time': current_time,
                    'message_id': message.message_id,
                    'message': signal
                }
        except Exception as e:
            print(f"Error processing {pair}: {str(e)}")
            continue

def start(update, context):
    update.message.reply_text("This bot is sending now trading signals in hundreds channels / to get it in your channel DM t.me/King_protradr")

def main():
    try:
        updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        # Add command handlers
        dp.add_handler(CommandHandler("start", start))

        job_queue = updater.job_queue

        # Schedule the job to run every 3 minutes
        job_queue.run_repeating(send_signal, interval=180, first=1)

        print("Bot started successfully! Press Ctrl+C to stop.")
        updater.start_polling()
        updater.idle()

    except Exception as e:
        print(f"Error starting bot: {str(e)}")

if __name__ == "__main__":
    main()
