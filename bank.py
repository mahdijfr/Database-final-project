from decimal import Decimal
import mysql.connector
import hashlib
import random
import string
from datetime import datetime

# Connect to MySQL database
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    passwd="",
    database="dbproject"
)
# Create a cursor object to execute SQL queries
c = conn.cursor()
# Create tables if not exists
c.execute('''CREATE TABLE IF NOT EXISTS Users (
                UserID INT AUTO_INCREMENT PRIMARY KEY,
                Fname VARCHAR(255),
                Lname VARCHAR(255),
                NationalID VARCHAR(255) UNIQUE,
                Username VARCHAR(255) UNIQUE,
                PasswordHash VARCHAR(255)
            )''')

c.execute('''CREATE TABLE IF NOT EXISTS BankAccounts (
    AccountID INT AUTO_INCREMENT PRIMARY KEY,
    UserID INT,
    CardNumber VARCHAR(16) UNIQUE,
    IBAN VARCHAR(22) UNIQUE,
    Balance DECIMAL(10, 2),
    CardToCardLimit DECIMAL(10, 2) DEFAULT 10000000,  -- Daily limit for card to card transfer (10 million tooman)
    SatnaLimit DECIMAL(10, 2) DEFAULT 1000000,     -- Daily limit for Satna transfer (100 million tooman)
    PayaLimit DECIMAL(10, 2) DEFAULT 10000000,      -- Daily limit for Paya transfer (100 million tooman)
    LastCardToCardDate DATE DEFAULT CURDATE(),       -- Last date of card to card transaction
    LastSatnaDate DATE DEFAULT CURDATE(),            -- Last date of Satna transaction
    LastPayaDate DATE DEFAULT CURDATE(),             -- Last date of Paya transaction
    FOREIGN KEY (UserID) REFERENCES Users(UserID)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS Transactions (
                TransactionID INT AUTO_INCREMENT PRIMARY KEY,
                SenderAccountID INT,
                ReceiverAccountID INT,
                Amount DECIMAL(10, 2),
                TransactionType VARCHAR(255),
                DateTime DATETIME DEFAULT CURRENT_TIMESTAMP,
                TrackingCode VARCHAR(255) UNIQUE,
                FOREIGN KEY (SenderAccountID) REFERENCES BankAccounts(AccountID),
                FOREIGN KEY (ReceiverAccountID) REFERENCES BankAccounts(AccountID)
            )''')



# Functions to interact with the database

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()
def login(username, password):
    hashed_password = hash_password(password)
    c.execute("SELECT UserID FROM Users WHERE Username=%s AND PasswordHash=%s",
              (username, hashed_password))
    user_id = c.fetchone()
    if user_id:
        return True, user_id[0]  # Return True for successful login and the user's ID
    else:
        return False, None  # Return False for unsuccessful login and None for user ID
    
def signup(fname, lname, username, password, national_id):
    hashed_password = hash_password(password)
    try:
        c.execute("INSERT INTO Users (Fname, Lname, NationalID, Username, PasswordHash) VALUES (%s, %s, %s, %s, %s)",
                  (fname, lname, national_id, username, hashed_password))
        conn.commit()
        return "Signup successful!"
    except mysql.connector.IntegrityError:
        return "Username or national ID already exists!"

def create_account(user_id, initial_balance):
    card_number = ''.join(random.choices(string.digits, k=16))
    iban = ''.join(random.choices(string.ascii_uppercase + string.digits, k=22))
    try:
        c.execute("INSERT INTO BankAccounts (UserID, CardNumber, IBAN, Balance) VALUES (%s, %s, %s, %s)",
                  (user_id, card_number, iban, initial_balance))
        conn.commit()
        account_id = c.lastrowid  # Get the ID of the last inserted row
        return f"Account created successfully! Account ID: {account_id}, Card Number: {card_number}, IBAN: {iban}", account_id
    except mysql.connector.Error as e:
        return f"Error creating account: {e}", None

def card_to_card_transaction(sender_card_number, receiver_card_number, amount):
    try:
        c.execute("SELECT * FROM BankAccounts WHERE CardNumber=%s", (sender_card_number,))
        sender_account = c.fetchone()
        c.execute("SELECT * FROM BankAccounts WHERE CardNumber=%s", (receiver_card_number,))
        receiver_account = c.fetchone()
        if sender_account and receiver_account:
            if sender_account[4] >= Decimal(amount):  # Convert amount to Decimal
                new_sender_balance = sender_account[4] - Decimal(amount)  # Convert amount to Decimal
                new_receiver_balance = receiver_account[4] + Decimal(amount)  # Convert amount to Decimal
                c.execute("UPDATE BankAccounts SET Balance=%s WHERE CardNumber=%s", (new_sender_balance, sender_card_number))
                c.execute("UPDATE BankAccounts SET Balance=%s WHERE CardNumber=%s", (new_receiver_balance, receiver_card_number))
                tracking_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))  # Use amount directly
                c.execute("INSERT INTO Transactions (SenderAccountID, ReceiverAccountID, Amount, TransactionType, TrackingCode) VALUES (%s, %s, %s, %s, %s)",
                          (sender_account[0], receiver_account[0], amount, 'Card to Card', tracking_code))
                conn.commit()
                return f"Transaction successful! Tracking Code: {tracking_code}"
            else:
                return "Insufficient balance!"
        else:
            return "Invalid card numbers!"
    except mysql.connector.Error as e:
        return f"Error during transaction: {e}"

def satna_transaction(sender_account_id, receiver_iban, amount):
    try:
        # Fetch sender's balance, Satna limit, and last Satna date
        c.execute("SELECT Balance, SatnaLimit, LastSatnaDate, TIMESTAMPDIFF(DAY, LastSatnaDate, CURDATE()) FROM BankAccounts WHERE AccountID=%s", (sender_account_id,))
        sender_data = c.fetchone()
        sender_balance, satna_limit, last_satna_date, days_diff = sender_data[0], sender_data[1], sender_data[2], sender_data[3]

        # Check if it's the next day from the last limit
        if days_diff >= 1:
            # Reset Satna limit and update last Satna date
            c.execute("UPDATE BankAccounts SET SatnaLimit=%s, LastSatnaDate=CURDATE() WHERE AccountID=%s", (Decimal('100000000'), sender_account_id))  # Use Decimal('100000000')
            conn.commit()
            satna_limit = Decimal('100000000')
            last_satna_date = datetime.now().date()

        # Check if amount exceeds the limit
        if amount > satna_limit:
            return f"Transaction amount exceeds the Satna limit of {satna_limit}."

        # Check if sender has enough balance
        if sender_balance >= Decimal(amount):  # Convert amount to Decimal
            # Fetch receiver's account ID using the IBAN
            c.execute("SELECT AccountID FROM BankAccounts WHERE IBAN=%s", (receiver_iban,))
            receiver_account_id = c.fetchone()
            if not receiver_account_id:
                return "Receiver's IBAN is invalid."

            receiver_account_id = receiver_account_id[0]

            # Deduct amount from sender's balance
            new_sender_balance = sender_balance - Decimal(amount)  # Convert amount to Decimal

            # Update sender's balance
            c.execute("UPDATE BankAccounts SET Balance=%s WHERE AccountID=%s", (new_sender_balance, sender_account_id))

            # Add amount to receiver's balance
            c.execute("UPDATE BankAccounts SET Balance=Balance+%s WHERE AccountID=%s", (Decimal(amount), receiver_account_id))  # Convert amount to Decimal
            tracking_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))  # Use amount directly
            c.execute("INSERT INTO Transactions (SenderAccountID, ReceiverAccountID, Amount, TransactionType, TrackingCode) VALUES (%s, %s, %s, %s, %s)",
                      (sender_account_id, receiver_account_id, amount, 'satna', tracking_code))
            # Commit the transaction
            conn.commit()
            return f"Transaction successful! Tracking Code: {tracking_code}"
        else:
            return "Not enough balance to perform the transaction."
    except mysql.connector.Error as e:
        return f"Transaction failed: {e}"
    
def get_user_bank_accounts(user_id):
    try:
        # Fetch column names
        c.execute("DESCRIBE BankAccounts")
        columns = [column[0] for column in c.fetchall()]

        # Fetch bank account details for the user
        c.execute("SELECT * FROM BankAccounts WHERE UserID=%s", (user_id,))
        bank_accounts = c.fetchall()
        if bank_accounts:
            # Combine column names and bank account details
            result = []
            for account in bank_accounts:
                formatted_account = "\n".join([f"{columns[i]} = {account[i]}" for i in range(len(columns))])
                result.append(formatted_account)
                result.append("--------------------------------")
            return "\n".join(result)
        else:
            return "No bank accounts found for the user."
    except mysql.connector.Error as e:
        return f"Error retrieving bank accounts: {e}"


def paya_transaction(sender_account_id, receiver_iban, amount):
    try:
        # Fetch sender's balance, Paya limit, and last Paya date
        c.execute("SELECT Balance, PayaLimit, LastPayaDate, TIMESTAMPDIFF(DAY, LastPayaDate, CURDATE()) FROM BankAccounts WHERE AccountID=%s", (sender_account_id,))
        sender_data = c.fetchone()
        sender_balance, paya_limit, last_paya_date, days_diff = sender_data[0], sender_data[1], sender_data[2], sender_data[3]

        # Check if it's the next day from the last limit
        if days_diff >= 1:
            # Reset Paya limit and update last Paya date
            c.execute("UPDATE BankAccounts SET PayaLimit=%s, LastPayaDate=CURDATE() WHERE AccountID=%s", (Decimal('100000000'), sender_account_id))
            conn.commit()
            paya_limit = Decimal('100000000')
            last_paya_date = datetime.now().date()

        # Check if amount exceeds the limit
        if Decimal(amount) > paya_limit:
            return f"Transaction amount exceeds the Paya limit of {paya_limit}."

        # Check if sender has enough balance
        if sender_balance >= Decimal(amount):
            # Fetch receiver's account ID using the IBAN
            c.execute("SELECT AccountID FROM BankAccounts WHERE IBAN=%s", (receiver_iban,))
            receiver_account_id = c.fetchone()
            if not receiver_account_id:
                return "Receiver's IBAN is invalid."

            receiver_account_id = receiver_account_id[0]

            # Deduct amount from sender's balance
            new_sender_balance = sender_balance - Decimal(amount)

            # Update sender's balance
            c.execute("UPDATE BankAccounts SET Balance=%s WHERE AccountID=%s", (new_sender_balance, sender_account_id))

            # Add amount to receiver's balance
            c.execute("UPDATE BankAccounts SET Balance=Balance+%s WHERE AccountID=%s", (Decimal(amount), receiver_account_id))
            tracking_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))  # Use amount directly
            c.execute("INSERT INTO Transactions (SenderAccountID, ReceiverAccountID, Amount, TransactionType, TrackingCode) VALUES (%s, %s, %s, %s, %s)",
                      (sender_account_id, receiver_account_id, amount, 'paya', tracking_code))
            # Commit the transaction
            conn.commit()
            return f"Transaction successful! Tracking Code: {tracking_code}"
        else:
            return "Not enough balance to perform the transaction."
    except mysql.connector.Error as e:
        return f"Transaction failed: {e}"
def get_last_transactions(account_id, n):
    try:
        c.execute("SELECT * FROM Transactions WHERE SenderAccountID=%s OR ReceiverAccountID=%s ORDER BY DateTime DESC LIMIT %s", (account_id, account_id, n))
        transactions = c.fetchall()
        
        if transactions:
            # Fetch column names
            c.execute("DESCRIBE Transactions")
            columns = [column[0] for column in c.fetchall()]

            # Format output with column names
            output = []
            for transaction in transactions:
                formatted_transaction = "\n".join([f"'{columns[i]}': {transaction[i]}" for i in range(len(columns))])
                output.append(formatted_transaction)
                output.append('-------')

            return output
        else:
            return "No transactions found."
    except mysql.connector.Error as e:
        print(f"Error fetching transactions: {e}")
        return None


def check_transaction_validity(tracking_code):
    try:
        c.execute("SELECT * FROM Transactions WHERE TrackingCode=%s", (tracking_code,))
        transaction = c.fetchone()
        if transaction:
            # Fetch column names
            c.execute("DESCRIBE Transactions")
            columns = [column[0] for column in c.fetchall()]

            # Format output with column names
            formatted_transaction = "\n".join([f"'{columns[i]}': {transaction[i]}" for i in range(len(columns))])
            return formatted_transaction
        else:
            return "No transaction found with the given tracking code."
    except mysql.connector.Error as e:
        print(f"Error checking transaction validity: {e}")
        return None

#ui 
# Create the main application window

def main():
    while True:
        print("\nMain Menu:")
        print("1. Login")
        print("2. Sign Up")
        print("3. Exit")
        option = input("Enter your choice: ")

        if option == '1':
            username = input("Enter your username: ")
            password = input("Enter your password: ")
            if login(username, password)[0] == True:
                print("Login successful!")
                user_menu(username,password)
            else:
                print("Invalid username or password!")
        elif option == '2':
            fname = input("Enter your first name: ")
            lname = input("Enter your last name: ")
            username = input("Choose a username: ")
            password = input("Choose a password: ")
            national_id = input("Enter your national ID: ")
            result = signup(fname, lname, username, password, national_id)
            print(result)
        elif option == '3':
            print("Exiting...")
            break
        else:
            print("Invalid option! Please choose a valid option.")



def user_menu(username,password):
    while True:
        print("\nUser Menu:")
        print("1. Create new account")
        print("2. Card to Card Transaction")
        print("3. Satna Transaction")
        print("4. Paya Transaction")
        print("5. Get last N transactions")
        print("6. Check transaction validity by tracking code")
        print("7. Get your accounts details")
        print("8. Logout")

        option = input("Enter your choice: ")


        if option == '1':
            initial_balance = float(input("Enter initial balance: "))
            logged_in, user_id = login(username, password)  # Assuming username and password are already obtained
            if logged_in:
                result = create_account(user_id, initial_balance)
                print(result)
            else:
                print("You need to log in before creating a new account.")
        elif option == '2':
                # Implement card to card transaction functionality
                sender_card_number = input("Enter sender's card number: ")
                receiver_card_number = input("Enter receiver's card number: ")
                amount = float(input("Enter amount: "))
                result = card_to_card_transaction(sender_card_number, receiver_card_number, amount)
                print(result)
        elif option == '3':
            sender_card_number = input("Enter your AccountId: ")
            receiver_iban = input("Enter receiver's IBAN: ")
            amount = float(input("Enter amount: "))
            result = satna_transaction(sender_card_number, receiver_iban, amount)
            print(result)
        elif option == '4':
            sender_card_number = input("Enter your AccountId: ")
            receiver_iban = input("Enter receiver's IBAN: ")
            amount = float(input("Enter amount: "))
            result = paya_transaction(sender_card_number, receiver_iban, amount)
            print(result)
        elif option == '5':
            account_id = input("Enter account ID: ")  # Assuming account ID is provided by the user
            n = int(input("Enter the number of transactions to retrieve: "))
            transactions = get_last_transactions(account_id, n)
            if transactions:
                print("Last", n, "transactions:")
                for transaction in transactions:
                    print(transaction)  # Modify as per your transaction format
            else:
                print("No transactions found.")
        elif option == '6':
            tracking_code = input("Enter tracking code: ")
            transaction = check_transaction_validity(tracking_code)
            if transaction:
                print(transaction)
                # Print transaction details
            else:
                print("Invalid tracking code!")
        elif option == '8':
            print("Logging out...")
            main()
            break
        elif option =='7':
            logged_in, user_id = login(username,password)
            print(get_user_bank_accounts(user_id))
        else:
            print("Invalid option! Please choose a valid option.")


if __name__ == "__main__":
    main()