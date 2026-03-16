import sqlite3
import os
import sys
from flask import Flask, render_template, request, redirect, url_for, session, g
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'simple_secret_key_for_demo'

DATABASE = 'cargo.db'

print("=== STARTING APP ===")
print("Current directory:", os.getcwd())
print("Files in directory:", os.listdir('.'))

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    print(">>> init_db() called")
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        print(">>> Creating tables...")
        # таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                phone TEXT,
                role TEXT NOT NULL,
                login TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                experience INTEGER,
                license_category TEXT
            )
        ''')
        # таблица транспортных средств
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate TEXT UNIQUE NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                body_type TEXT NOT NULL,
                capacity REAL NOT NULL,
                status TEXT DEFAULT 'свободно',
                current_driver_id INTEGER,
                FOREIGN KEY (current_driver_id) REFERENCES users(id)
            )
        ''')
        # таблица заказов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                driver_id INTEGER,
                pickup TEXT NOT NULL,
                destination TEXT NOT NULL,
                datetime TEXT NOT NULL,
                cargo_description TEXT,
                required_body_type TEXT NOT NULL,
                status TEXT DEFAULT 'создан',
                vehicle_id INTEGER,
                FOREIGN KEY (customer_id) REFERENCES users(id),
                FOREIGN KEY (driver_id) REFERENCES users(id),
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
            )
        ''')
        db.commit()
        print(">>> Tables created (if not existed)")

init_db()

# ------------------------------------------------------------
# Маршруты
# ------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        phone = request.form['phone']
        role = request.form['role']
        login = request.form['login']
        password = request.form['password']
        experience = request.form.get('experience')
        license_category = request.form.get('license_category')
        db = get_db()
        try:
            db.execute('INSERT INTO users (full_name, phone, role, login, password, experience, license_category) VALUES (?,?,?,?,?,?,?)',
                       (full_name, phone, role, login, password, experience, license_category))
            db.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return 'Логин уже существует'
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login = request.form['login']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE login=? AND password=?', (login, password)).fetchone()
        if user:
            session['user_id'] = user['id']
            session['role'] = user['role']
            if user['role'] == 'customer':
                return redirect(url_for('customer_dashboard'))
            elif user['role'] == 'driver':
                return redirect(url_for('driver_dashboard'))
            elif user['role'] == 'dispatcher':
                return redirect(url_for('dispatcher_dashboard'))
        return 'Неверный логин или пароль'
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ----- Заказчик -----
@app.route('/customer')
def customer_dashboard():
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    return render_template('customer_dashboard.html')

@app.route('/create_order', methods=['GET', 'POST'])
def create_order():
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    if request.method == 'POST':
        pickup = request.form['pickup']
        destination = request.form['destination']
        dt = request.form['datetime']
        cargo_desc = request.form['cargo_description']
        body_type = request.form['body_type']
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO orders (customer_id, pickup, destination, datetime, cargo_description, required_body_type, status)
            VALUES (?, ?, ?, ?, ?, ?, 'создан')
        ''', (session['user_id'], pickup, destination, dt, cargo_desc, body_type))
        db.commit()
        order_id = cursor.lastrowid
        return redirect(url_for('choose_vehicle', order_id=order_id))
    return render_template('create_order.html')

@app.route('/choose_vehicle/<int:order_id>')
def choose_vehicle(order_id):
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order or order['customer_id'] != session['user_id']:
        return 'Заказ не найден'
    vehicles = db.execute('''
        SELECT * FROM vehicles 
        WHERE status='свободно' AND body_type=?
    ''', (order['required_body_type'],)).fetchall()
    return render_template('choose_vehicle.html', order=order, vehicles=vehicles)

@app.route('/assign_vehicle/<int:order_id>/<int:vehicle_id>')
def assign_vehicle(order_id, vehicle_id):
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    db = get_db()
    vehicle = db.execute('SELECT * FROM vehicles WHERE id=? AND status="свободно"', (vehicle_id,)).fetchone()
    if not vehicle:
        return 'Транспортное средство недоступно'
    db.execute('UPDATE orders SET vehicle_id=? WHERE id=?', (vehicle_id, order_id))
    db.execute('UPDATE vehicles SET status="в рейсе" WHERE id=?', (vehicle_id,))
    db.commit()
    return redirect(url_for('my_orders'))

@app.route('/my_orders')
def my_orders():
    if session.get('role') != 'customer':
        return redirect(url_for('login'))
    db = get_db()
    orders = db.execute('''
        SELECT o.*, v.plate, v.brand, v.model, u.full_name as driver_name
        FROM orders o
        LEFT JOIN vehicles v ON o.vehicle_id = v.id
        LEFT JOIN users u ON o.driver_id = u.id
        WHERE o.customer_id=?
        ORDER BY o.datetime DESC
    ''', (session['user_id'],)).fetchall()
    return render_template('my_orders.html', orders=orders)

# ----- Водитель -----
@app.route('/driver')
def driver_dashboard():
    if session.get('role') != 'driver':
        return redirect(url_for('login'))
    return render_template('driver_dashboard.html')

@app.route('/available_orders')
def available_orders():
    if session.get('role') != 'driver':
        return redirect(url_for('login'))
    db = get_db()
    orders = db.execute('''
        SELECT o.*, v.plate, v.brand, v.model
        FROM orders o
        JOIN vehicles v ON o.vehicle_id = v.id
        WHERE o.status='создан'
    ''').fetchall()
    return render_template('available_orders.html', orders=orders)

@app.route('/accept_order/<int:order_id>')
def accept_order(order_id):
    if session.get('role') != 'driver':
        return redirect(url_for('login'))
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=? AND status="создан"', (order_id,)).fetchone()
    if not order:
        return 'Заказ недоступен'
    db.execute('UPDATE orders SET driver_id=?, status="принят" WHERE id=?', (session['user_id'], order_id))
    db.commit()
    return redirect(url_for('available_orders'))

@app.route('/complete_order/<int:order_id>')
def complete_order(order_id):
    if session.get('role') != 'driver':
        return redirect(url_for('login'))
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=? AND driver_id=? AND status="принят"', (order_id, session['user_id'])).fetchone()
    if not order:
        return 'Заказ недоступен'
    db.execute('UPDATE orders SET status="выполнен" WHERE id=?', (order_id,))
    if order['vehicle_id']:
        db.execute('UPDATE vehicles SET status="свободно" WHERE id=?', (order['vehicle_id'],))
    db.commit()
    return redirect(url_for('driver_dashboard'))

# ----- Диспетчер -----
@app.route('/dispatcher')
def dispatcher_dashboard():
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    return render_template('dispatcher_dashboard.html')

@app.route('/vehicles')
def vehicles():
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    db = get_db()
    vehicles = db.execute('''
        SELECT v.*, u.full_name as driver_name
        FROM vehicles v
        LEFT JOIN users u ON v.current_driver_id = u.id
    ''').fetchall()
    return render_template('vehicles.html', vehicles=vehicles)

@app.route('/add_vehicle', methods=['GET', 'POST'])
def add_vehicle():
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    if request.method == 'POST':
        plate = request.form['plate']
        brand = request.form['brand']
        model = request.form['model']
        body_type = request.form['body_type']
        capacity = request.form['capacity']
        db = get_db()
        try:
            db.execute('INSERT INTO vehicles (plate, brand, model, body_type, capacity, status) VALUES (?,?,?,?,?, "свободно")',
                       (plate, brand, model, body_type, capacity))
            db.commit()
        except sqlite3.IntegrityError:
            return 'Такой госномер уже существует'
        return redirect(url_for('vehicles'))
    return render_template('add_vehicle.html')

@app.route('/delete_vehicle/<int:vehicle_id>')
def delete_vehicle(vehicle_id):
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    db = get_db()
    db.execute('DELETE FROM vehicles WHERE id=?', (vehicle_id,))
    db.commit()
    return redirect(url_for('vehicles'))

@app.route('/drivers')
def drivers():
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    db = get_db()
    drivers = db.execute('SELECT * FROM users WHERE role="driver"').fetchall()
    return render_template('drivers.html', drivers=drivers)

@app.route('/assign_driver/<int:vehicle_id>', methods=['GET', 'POST'])
def assign_driver(vehicle_id):
    if session.get('role') != 'dispatcher':
        return redirect(url_for('login'))
    db = get_db()
    vehicle = db.execute('SELECT * FROM vehicles WHERE id=?', (vehicle_id,)).fetchone()
    if not vehicle:
        return 'ТС не найдено'
    if request.method == 'POST':
        driver_id = request.form['driver_id']
        db.execute('UPDATE vehicles SET current_driver_id=? WHERE id=?', (driver_id, vehicle_id))
        db.commit()
        return redirect(url_for('vehicles'))
    drivers = db.execute('SELECT id, full_name FROM users WHERE role="driver"').fetchall()
    return render_template('assign_driver.html', vehicle=vehicle, drivers=drivers)

if __name__ == '__main__':
    app.run(debug=True)
