from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from cryptography.fernet import Fernet

from .errors import Denied


class Store:
    def __init__(self, path: str, key: str):
        self.path, self.cipher = path, Fernet(key.encode())
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS intents (
                    id TEXT PRIMARY KEY, document BLOB NOT NULL, digest TEXT NOT NULL,
                    status TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS grants (
                    id TEXT PRIMARY KEY, intent_id TEXT UNIQUE NOT NULL,
                    digest TEXT NOT NULL, expires_at INTEGER NOT NULL, consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    intent_id TEXT PRIMARY KEY, day TEXT NOT NULL, total_minor INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, intent_id TEXT, action TEXT, reason TEXT, occurred_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS private_orders (
                    id TEXT PRIMARY KEY, document BLOB NOT NULL, txid TEXT UNIQUE, redeemed_at INTEGER
                );
            """)
            # Never silently retry calls interrupted by a process crash.
            db.execute("UPDATE intents SET status='UNCERTAIN' WHERE status='EXECUTING'")
        os.chmod(path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def seal(self, value):
        return self.cipher.encrypt(json.dumps(value, allow_nan=False).encode())

    def open(self, value):
        return json.loads(self.cipher.decrypt(value))

    def event(self, intent_id, action, reason, db=None):
        if db is None:
            with self.connect() as connection:
                self.event(intent_id, action, reason, connection)
        else:
            db.execute("INSERT INTO audit(intent_id, action, reason, occurred_at) VALUES(?,?,?,?)",
                       (intent_id, action, reason, int(time.time())))

    def insert_intent(self, intent):
        with self.transaction() as db:
            db.execute("INSERT INTO intents VALUES(?,?,?,?,?,?)",
                       (intent["id"], self.seal(intent), intent["digest"], intent["status"],
                        intent["expires_at"], intent["created_at"]))
            self.event(intent["id"], "propose", "POLICY_PASSED", db)

    def intent(self, intent_id, db=None):
        if db is None:
            with self.connect() as connection:
                return self.intent(intent_id, connection)
        row = db.execute("SELECT * FROM intents WHERE id=?", (intent_id,)).fetchone()
        if row is None:
            raise Denied("NOT_FOUND", "Intent not found.", 404)
        value = self.open(row["document"])
        value["status"] = row["status"]
        return value

    def save_intent(self, intent, db=None):
        if db is None:
            with self.transaction() as connection:
                return self.save_intent(intent, connection)
        db.execute("UPDATE intents SET document=?, status=? WHERE id=?",
                   (self.seal(intent), intent["status"], intent["id"]))

    def list_intents(self):
        with self.connect() as db:
            ids = db.execute("SELECT id FROM intents ORDER BY created_at DESC LIMIT 100").fetchall()
            return [self.intent(row["id"], db) for row in ids]

    def approve(self, intent_id, expected_digest, ttl):
        now, grant_id = int(time.time()), "gr_" + uuid.uuid4().hex
        with self.transaction() as db:
            intent = self.intent(intent_id, db)
            if intent["digest"] != expected_digest:
                raise Denied("APPROVAL_MISMATCH", "Approval does not match the displayed intent.")
            if intent["status"] != "AWAITING_APPROVAL":
                raise Denied("ALREADY_APPROVED", "This intent cannot be approved again.")
            if intent["expires_at"] <= now:
                raise Denied("QUOTE_EXPIRED", "Quote expired. Create a fresh intent.")
            expires = min(now + ttl, intent["expires_at"])
            db.execute("INSERT INTO grants VALUES(?,?,?,?,NULL)", (grant_id, intent_id, expected_digest, expires))
            intent["status"] = "AUTHORIZED"
            self.save_intent(intent, db)
            self.event(intent_id, "approve", "EXACT_INTENT_APPROVED", db)
        return grant_id, expires

    def reserve(self, intent_id, claims, day, daily_cap):
        now = int(time.time())
        with self.transaction() as db:
            intent = self.intent(intent_id, db)
            row = db.execute("SELECT * FROM grants WHERE id=?", (claims["jti"],)).fetchone()
            if row is None or row["intent_id"] != intent_id or row["digest"] != intent["digest"]:
                raise Denied("INVALID_GRANT", "Grant is not bound to this intent.")
            if row["consumed_at"] is not None:
                raise Denied("GRANT_REPLAY", "Grant already consumed. No second purchase was attempted.")
            if row["expires_at"] <= now or intent["expires_at"] <= now:
                raise Denied("GRANT_EXPIRED", "This approval expired.")
            if intent["status"] != "AUTHORIZED":
                raise Denied("INVALID_STATE", "Intent is not executable.")
            # Reserve the APPROVED MAXIMUM, including any permitted quote increase.
            amount = intent["action"]["max_total_minor"]
            spent = db.execute("SELECT COALESCE(SUM(total_minor),0) FROM reservations WHERE day=?", (day,)).fetchone()[0]
            if spent + amount > daily_cap:
                raise Denied("DAILY_CAP", "Daily reserved spend cap reached. Nothing was purchased.")
            db.execute("INSERT INTO reservations VALUES(?,?,?)", (intent_id, day, amount))
            db.execute("UPDATE grants SET consumed_at=? WHERE id=?", (now, row["id"]))
            intent["status"] = "EXECUTING"
            self.save_intent(intent, db)
            self.event(intent_id, "execute", "GRANT_CONSUMED_AND_BUDGET_RESERVED", db)
        return intent

    def audit(self, intent_id):
        self.intent(intent_id)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT action,reason,occurred_at FROM audit WHERE intent_id=? ORDER BY id", (intent_id,))]

    def insert_private(self, order):
        with self.connect() as db:
            db.execute("INSERT INTO private_orders VALUES(?,?,NULL,NULL)", (order["id"], self.seal(order)))

    def private(self, order_id, db=None):
        if db is None:
            with self.connect() as connection:
                return self.private(order_id, connection)
        row = db.execute("SELECT * FROM private_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise Denied("NOT_FOUND", "Private order not found.", 404)
        order = self.open(row["document"])
        if row["redeemed_at"] is not None:
            order["status"] = "REDEEMED"
        return order

    def confirm_private(self, order_id, payment):
        try:
            with self.transaction() as db:
                order = self.private(order_id, db)
                if order["status"] != "AWAITING_PAYMENT":
                    return order
                order.update(status="CONFIRMED", payment=payment, entitlement_expires_at=int(time.time()) + 300)
                db.execute("UPDATE private_orders SET document=?,txid=? WHERE id=?",
                           (self.seal(order), payment["txid"], order_id))
            return order
        except sqlite3.IntegrityError:
            raise Denied("PAYMENT_CONFLICT", "This transaction already fulfilled another order.") from None

    def redeem(self, order_id):
        with self.transaction() as db:
            order = self.private(order_id, db)
            if order["status"] != "CONFIRMED":
                raise Denied("NOT_REDEEMABLE", "A confirmed payment and unused entitlement are required.")
            if order.get("entitlement_expires_at", 0) <= int(time.time()):
                raise Denied("ENTITLEMENT_EXPIRED", "The five-minute entitlement expired.")
            db.execute("UPDATE private_orders SET redeemed_at=? WHERE id=?", (int(time.time()), order_id))
            self.event(order_id, "redeem", "ENTITLEMENT_CONSUMED", db)
