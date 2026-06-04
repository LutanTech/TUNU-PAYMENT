import base64
import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = 'THIS_IS_SO_SECRET_FOR_2026_TUNU'
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DB_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# MPESA CONFIG
CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")
SHORTCODE = os.getenv("MPESA_SHORTCODE")
PASSKEY = os.getenv("MPESA_PASSKEY")
MPESA_ENV = os.getenv("MPESA_ENV", "sandbox")

BASE_URL = (
    "https://sandbox.safaricom.co.ke"
    if MPESA_ENV == "sandbox"
    else "https://api.safaricom.co.ke"
)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    checkout_request_id = db.Column(db.String(100), unique=True)
    merchant_request_id = db.Column(db.String(100))

    phone = db.Column(db.String(20))
    amount = db.Column(db.Float)

    receipt = db.Column(db.String(50))

    status = db.Column(db.String(20), default="PENDING")

    result_code = db.Column(db.Integer)
    result_desc = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def format_phone(phone):
    phone = str(phone).replace("+", "").strip()

    if phone.startswith("0"):
        phone = "254" + phone[1:]

    elif phone.startswith("7"):
        phone = "254" + phone

    return phone


def get_access_token():
    url = f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials"

    response = requests.get(
        url,
        auth=(CONSUMER_KEY, CONSUMER_SECRET)
    )

    response.raise_for_status()

    return response.json()["access_token"]


def stk_push(phone, amount):

    phone = format_phone(phone)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    password = base64.b64encode(
        f"{SHORTCODE}{PASSKEY}{timestamp}".encode()
    ).decode()

    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": "https://pay.tunupublishers.com/mpesa/callback",
        "AccountReference": "Tunu Publishers",
        "TransactionDesc": "Book(s) Purchase"
    }

    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{BASE_URL}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers=headers
    )

    data = response.json()

    if data.get("ResponseCode") == "0":

        payment = Payment(
            phone=phone,
            amount=amount,
            checkout_request_id=data.get("CheckoutRequestID"),
            merchant_request_id=data.get("MerchantRequestID"),
            status="PENDING"
        )

        db.session.add(payment)
        db.session.commit()

    return data


@app.route("/api/pay", methods=["POST"])
def pay_route():

    data = request.get_json()

    phone = data.get("phone")
    amount = data.get("amount")

    if not phone or not amount:
        return jsonify({
            "success": False,
            "message": "Phone and amount required"
        }), 400

    result = stk_push(phone, amount)

    return jsonify(result)


@app.route("/mpesa/callback", methods=["POST"])
def mpesa_callback():

    data = request.get_json(force=True)

    print(json.dumps(data, indent=2))

    stk = data.get("Body", {}).get("stkCallback", {})

    checkout_request_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc")

    payment = Payment.query.filter_by(
        checkout_request_id=checkout_request_id
    ).first()

    if payment:

        payment.result_code = result_code
        payment.result_desc = result_desc

        if result_code == 0:

            metadata = stk.get(
                "CallbackMetadata",
                {}
            ).get("Item", [])

            parsed = {
                item["Name"]: item.get("Value")
                for item in metadata
            }

            payment.amount = parsed.get(
                "Amount",
                payment.amount
            )

            payment.phone = str(
                parsed.get(
                    "PhoneNumber",
                    payment.phone
                )
            )

            payment.receipt = parsed.get(
                "MpesaReceiptNumber"
            )

            payment.status = "SUCCESS"

        else:
            payment.status = "FAILED"

        db.session.commit()

    return jsonify({
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    })


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(debug=True)