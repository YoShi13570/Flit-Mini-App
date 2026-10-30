import os, json, time, hmac, hashlib, sqlite3
from urllib.parse import parse_qsl
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
# Read a local .env file without requiring an extra dependency.
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DB_PATH = Path(os.getenv("GAME_BOT_DB", str(ROOT / "game_bot.db"))).expanduser()
DEMO_MODE = os.getenv("MINIAPP_DEMO", "0") == "1"

app = FastAPI(title="FLIT Dark Luxury Mini App", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

def db():
    if not DB_PATH.exists():
        raise HTTPException(503, "Database not found. Put this app beside game_bot.db or set GAME_BOT_DB.")
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con

def verify_init_data(init_data: str):
    if DEMO_MODE and not init_data:
        return {"id": 100000001, "first_name": "Demo Player", "username": "demo"}
    if not BOT_TOKEN:
        raise HTTPException(503, "BOT_TOKEN is not configured.")
    if not init_data:
        raise HTTPException(401, "Open this Mini App from Telegram.")
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            raise ValueError("Missing hash")
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise ValueError("Invalid signature")
        auth_date = int(pairs.get("auth_date", "0"))
        if time.time() - auth_date > 86400:
            raise ValueError("Authentication expired")
        user = json.loads(pairs["user"])
        if not user.get("id"):
            raise ValueError("Invalid user")
        return user
    except Exception as exc:
        raise HTTPException(401, f"Telegram authentication failed: {exc}")

def current_user(authorization: Optional[str]):
    token = (authorization or "").removeprefix("tma ").strip()
    if DEMO_MODE and not token:
        return verify_init_data("")
    return verify_init_data(token)

def ensure_user(con, user):
    uid = int(user["id"])
    con.execute(
        "INSERT OR IGNORE INTO users(user_id,username,first_name,coins) VALUES(?,?,?,10000)",
        (uid, user.get("username"), user.get("first_name") or "Player")
    )
    con.execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (user.get("username"), user.get("first_name") or "Player", uid)
    )
    return uid

def rowdict(row):
    return dict(row) if row else None

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "db_exists": DB_PATH.exists(), "demo": DEMO_MODE}

@app.get("/api/me")
def me(authorization: Optional[str] = Header(default=None)):
    user = current_user(authorization)
    if DEMO_MODE and int(user["id"]) == 100000001:
        return {"user":{"id":user["id"],"name":user["first_name"],"username":"demo"},
                "wallet":{"coins":125000,"gems":420},"profile":{"level":18,"xp":1740,"wins":42,"losses":19,"games":61,"unique":37,"copies":52}}
    con = db()
    try:
        uid = ensure_user(con, user)
        con.execute("CREATE TABLE IF NOT EXISTS user_xp(user_id INTEGER PRIMARY KEY, xp INTEGER NOT NULL DEFAULT 0)")
        xp_row = con.execute("SELECT xp FROM user_xp WHERE user_id=?", (uid,)).fetchone()
        xp = int(xp_row["xp"]) if xp_row else 0
        wallet = con.execute("SELECT coins,gemstones,wins,losses,games FROM users WHERE user_id=?", (uid,)).fetchone()
        counts = con.execute("SELECT COUNT(DISTINCT character_id) unique_count,COALESCE(SUM(quantity),0) copies FROM owned_characters WHERE user_id=?", (uid,)).fetchone()
        con.commit()
        return {"user":{"id":uid,"name":user.get("first_name") or "Player","username":user.get("username")},
                "wallet":{"coins":int(wallet["coins"] or 0),"gems":int(wallet["gemstones"] or 0)},
                "profile":{"level":xp//100+1,"xp":xp,"wins":int(wallet["wins"] or 0),"losses":int(wallet["losses"] or 0),"games":int(wallet["games"] or 0),
                           "unique":int(counts["unique_count"] or 0),"copies":int(counts["copies"] or 0)}}
    finally:
        con.close()

@app.get("/api/harem")
def harem(authorization: Optional[str] = Header(default=None), q: str = "", rarity: str = "", page: int = 1):
    user = current_user(authorization); uid = int(user["id"])
    if DEMO_MODE and uid == 100000001:
        sample = [{"id":101,"name":"Mikasa Ackerman","anime":"Attack on Titan","rarity":"Divine","type":"Classic","quantity":2,"value_min":1500,"value_max":3000},
                  {"id":102,"name":"Gojo Satoru","anime":"Jujutsu Kaisen","rarity":"Supreme","type":"Shogun","quantity":1,"value_min":7000,"value_max":9000}]
        return {"items":sample,"page":1,"pages":1,"total":2}
    con = db()
    try:
        params = [uid]
        where = ["o.user_id=?", "o.quantity>0"]
        if q.strip():
            where.append("(c.name LIKE ? OR c.anime LIKE ? OR CAST(c.id AS TEXT)=?)")
            params.extend([f"%{q.strip()}%",f"%{q.strip()}%",q.strip()])
        if rarity.strip():
            where.append("c.rarity=?"); params.append(rarity.strip())
        clause = " AND ".join(where)
        total = con.execute(f"SELECT COUNT(*) FROM owned_characters o JOIN characters c ON c.id=o.character_id WHERE {clause}", params).fetchone()[0]
        page = max(1, page); limit = 12
        rows = con.execute(f"""SELECT c.id,c.name,c.anime,c.rarity,c.type,c.value_min,c.value_max,o.quantity
            FROM owned_characters o JOIN characters c ON c.id=o.character_id
            WHERE {clause} ORDER BY c.id DESC LIMIT ? OFFSET ?""", params+[limit,(page-1)*limit]).fetchall()
        return {"items":[rowdict(r) for r in rows],"page":page,"pages":max(1,(total+limit-1)//limit),"total":total}
    finally: con.close()

@app.get("/api/market")
def market(authorization: Optional[str] = Header(default=None), q: str = "", currency: str = "all"):
    user = current_user(authorization)
    if DEMO_MODE and int(user["id"]) == 100000001:
        return {"items":[{"code":"M248631","character_id":102,"name":"Gojo Satoru","anime":"Jujutsu Kaisen","rarity":"Supreme","seller_id":2001,"price":8200,"currency":"coins"},
                         {"code":"M248632","character_id":103,"name":"Hiyuki","anime":"Kagurabachi","rarity":"Divine","seller_id":2002,"price":180,"currency":"gemstones"}]}
    con = db()
    try:
        sql = """SELECT m.code,m.character_id,m.seller_id,m.price,m.currency,m.created_at,
                 c.name,c.anime,c.rarity,c.type,u.first_name seller_name
                 FROM character_market m JOIN characters c ON c.id=m.character_id
                 LEFT JOIN users u ON u.user_id=m.seller_id WHERE m.status='active'"""
        args=[]
        if q.strip():
            sql += " AND (c.name LIKE ? OR c.anime LIKE ? OR m.code LIKE ?)"
            args += [f"%{q.strip()}%",f"%{q.strip()}%",f"%{q.strip()}%"]
        if currency in ("coins","gemstones"):
            sql += " AND m.currency=?"; args.append(currency)
        sql += " ORDER BY m.created_at DESC LIMIT 100"
        return {"items":[rowdict(r) for r in con.execute(sql,args).fetchall()]}
    finally: con.close()

class BuyRequest(BaseModel):
    code: str

@app.post("/api/market/buy")
def market_buy(data: BuyRequest, authorization: Optional[str] = Header(default=None)):
    user = current_user(authorization); buyer = int(user["id"])
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_user(con, user)
        row = con.execute("SELECT * FROM character_market WHERE code=? AND status='active'", (data.code.upper(),)).fetchone()
        if not row: raise HTTPException(404,"Listing is no longer available.")
        seller,cid,price = int(row["seller_id"]),int(row["character_id"]),int(row["price"])
        wallet = "gemstones" if row["currency"] == "gemstones" else "coins"
        if seller == buyer: raise HTTPException(400,"You cannot buy your own listing.")
        buyer_row = con.execute(f"SELECT {wallet} FROM users WHERE user_id=?", (buyer,)).fetchone()
        seller_row = con.execute(f"SELECT {wallet} FROM users WHERE user_id=?", (seller,)).fetchone()
        owned = con.execute("SELECT quantity FROM owned_characters WHERE user_id=? AND character_id=?", (seller,cid)).fetchone()
        if not buyer_row or int(buyer_row[wallet] or 0) < price: raise HTTPException(400,"Not enough balance.")
        if not seller_row or not owned or int(owned["quantity"]) < 1: raise HTTPException(409,"Seller ownership could not be verified.")
        con.execute(f"UPDATE users SET {wallet}={wallet}-? WHERE user_id=?", (price,buyer))
        con.execute(f"UPDATE users SET {wallet}={wallet}+? WHERE user_id=?", (price,seller))
        con.execute("UPDATE owned_characters SET quantity=quantity-1 WHERE user_id=? AND character_id=?", (seller,cid))
        con.execute("DELETE FROM owned_characters WHERE user_id=? AND character_id=? AND quantity<=0",(seller,cid))
        con.execute("""INSERT INTO owned_characters(user_id,character_id,quantity) VALUES(?,?,1)
            ON CONFLICT(user_id,character_id) DO UPDATE SET quantity=owned_characters.quantity+1,last_caught_at=CURRENT_TIMESTAMP""",(buyer,cid))
        cur = con.execute("UPDATE character_market SET status='sold' WHERE code=? AND status='active'",(data.code.upper(),))
        if cur.rowcount != 1: raise HTTPException(409,"Listing changed. Refresh and retry.")
        con.execute("INSERT INTO transaction_logs(kind,sender_id,recipient_id,amount,character_id,quantity,details) VALUES(?,?,?,?,?,?,?)",
                    ("market_buy",buyer,seller,price,cid,1,f"Market code {data.code.upper()} ({wallet})"))
        con.commit()
        return {"ok":True,"message":"Purchase completed. Character added to your Harem."}
    except HTTPException:
        con.rollback(); raise
    except Exception:
        con.rollback(); raise HTTPException(500,"Purchase failed safely. No changes were saved.")
    finally: con.close()

class SellRequest(BaseModel):
    character_id: int
    price: int
    currency: str = "coins"

@app.post("/api/market/sell")
def market_sell(data: SellRequest, authorization: Optional[str] = Header(default=None)):
    user = current_user(authorization); uid=int(user["id"])
    if data.price <= 0 or data.currency not in ("coins","gemstones"):
        raise HTTPException(400,"Invalid price or currency.")
    con=db()
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_user(con, user)
        char=con.execute("SELECT * FROM characters WHERE id=?",(data.character_id,)).fetchone()
        own=con.execute("SELECT quantity,locked FROM owned_characters WHERE user_id=? AND character_id=?",(uid,data.character_id)).fetchone()
        if not char or not own or int(own["quantity"]) < 1: raise HTTPException(404,"You do not own this character.")
        if int(own["locked"] or 0): raise HTTPException(400,"This character is locked.")
        if con.execute("SELECT 1 FROM auctions WHERE character_id=? AND status='active'",(data.character_id,)).fetchone(): raise HTTPException(400,"This character is already in an auction.")
        if con.execute("SELECT 1 FROM character_market WHERE character_id=? AND status='active'",(data.character_id,)).fetchone(): raise HTTPException(400,"This character is already listed.")
        if char["rarity"]=="Infinity" and data.currency!="gemstones": raise HTTPException(400,"Infinity characters can only be listed for Gems.")
        if data.currency=="coins":
            # Match the exact coin value bands configured in the existing v14 bot.
            limits={"Common":(100,500),"Uncommon":(500,1200),"Rare":(1200,3000),"Legendary":(3000,8000),
                    "Mythical":(8000,18000),"Divine":(18000,35000),"Cataphract":(35000,60000),
                    "Crossverse":(60000,90000),"Supreme":(90000,130000),"Universal":(130000,160000)}
        else:
            limits={"Common":(1,10),"Uncommon":(5,25),"Rare":(10,50),"Legendary":(25,100),"Mythical":(50,180),"Divine":(75,300),"Cataphract":(100,450),"Crossverse":(150,650),"Supreme":(200,800),"Universal":(250,950),"Infinity":(1,1000000)}
        lo,hi=limits.get(char["rarity"],(1,1000000))
        if not lo <= data.price <= hi: raise HTTPException(400,f"Price range for {char['rarity']}: {lo:,}–{hi:,}.")
        wallet=con.execute("SELECT coins FROM users WHERE user_id=?",(uid,)).fetchone()
        if not wallet or int(wallet["coins"]) < 65: raise HTTPException(400,"Listing fee is 65 Coins.")
        con.execute("UPDATE users SET coins=coins-65 WHERE user_id=?",(uid,))
        code="M"+str(int(time.time()*1000)%900000+100000)
        while con.execute("SELECT 1 FROM character_market WHERE code=?",(code,)).fetchone():
            code="M"+str((int(code[1:])+1)%900000+100000)
        con.execute("INSERT INTO character_market(code,character_id,seller_id,price,currency) VALUES(?,?,?,?,?)",(code,data.character_id,uid,data.price,data.currency))
        con.execute("INSERT INTO transaction_logs(kind,sender_id,recipient_id,amount,character_id,quantity,details) VALUES(?,?,?,?,?,?,?)",
                    ("market_list",uid,uid,65,data.character_id,1,f"Listing {code}; asking {data.price} {data.currency}"))
        con.commit()
        return {"ok":True,"code":code,"message":f"Listed successfully. 65 Coins listing fee charged."}
    except HTTPException:
        con.rollback(); raise
    except Exception:
        con.rollback(); raise HTTPException(500,"Listing failed safely.")
    finally: con.close()

class WithdrawRequest(BaseModel):
    code: str

@app.post("/api/market/withdraw")
def market_withdraw(data: WithdrawRequest, authorization: Optional[str] = Header(default=None)):
    user=current_user(authorization); uid=int(user["id"]); con=db()
    try:
        con.execute("BEGIN IMMEDIATE")
        row=con.execute("SELECT * FROM character_market WHERE code=? AND status='active'",(data.code.upper(),)).fetchone()
        if not row or int(row["seller_id"])!=uid: raise HTTPException(404,"Your active listing was not found.")
        own=con.execute("SELECT quantity FROM owned_characters WHERE user_id=? AND character_id=?",(uid,int(row["character_id"]))).fetchone()
        if not own or int(own["quantity"])<1: raise HTTPException(409,"Ownership check failed.")
        con.execute("UPDATE character_market SET status='withdrawn' WHERE code=?",(data.code.upper(),))
        con.commit(); return {"ok":True,"message":"Listing withdrawn. Character remains in your Harem."}
    except HTTPException:
        con.rollback(); raise
    finally: con.close()

@app.get("/api/auctions")
def auctions(authorization: Optional[str] = Header(default=None)):
    current_user(authorization)
    if DEMO_MODE: return {"items":[{"auction_id":21,"character_id":102,"name":"Gojo Satoru","anime":"Jujutsu Kaisen","rarity":"Supreme","highest_bid":9500,"starting_price":5000,"ends_at":time.time()+3600,"highest_bidder_id":0,"seller_id":3001}]}
    con=db()
    try:
        rows=con.execute("""SELECT a.auction_id,a.character_id,a.seller_id,a.highest_bidder_id,a.highest_bid,a.starting_price,a.ends_at,
            c.name,c.anime,c.rarity,c.type FROM auctions a JOIN characters c ON c.id=a.character_id
            WHERE a.status='active' AND a.ends_at>? ORDER BY a.ends_at ASC LIMIT 100""",(time.time(),)).fetchall()
        return {"items":[rowdict(r) for r in rows]}
    finally: con.close()

class BidRequest(BaseModel):
    auction_id: int
    bid: int

@app.post("/api/auction/bid")
def auction_bid(data: BidRequest, authorization: Optional[str] = Header(default=None)):
    user=current_user(authorization); uid=int(user["id"])
    if data.bid <= 0: raise HTTPException(400,"Bid must be positive.")
    con=db()
    try:
        con.execute("BEGIN IMMEDIATE")
        ensure_user(con, user)
        auction=con.execute("SELECT * FROM auctions WHERE auction_id=? AND status='active'",(data.auction_id,)).fetchone()
        if not auction or float(auction["ends_at"])<=time.time(): raise HTTPException(404,"Auction has ended.")
        if int(auction["seller_id"])==uid: raise HTTPException(400,"You cannot bid on your own auction.")
        current=int(auction["highest_bid"]); old_bidder=auction["highest_bidder_id"]
        if data.bid<=current: raise HTTPException(400,f"Bid must exceed {current:,} Coins.")
        required=data.bid-current if old_bidder and int(old_bidder)==uid else data.bid
        wallet=con.execute("SELECT coins FROM users WHERE user_id=?",(uid,)).fetchone()
        if not wallet or int(wallet["coins"] or 0)<required: raise HTTPException(400,"Not enough Coins.")
        con.execute("UPDATE users SET coins=coins-? WHERE user_id=?",(required,uid))
        if old_bidder and int(old_bidder)!=uid:
            con.execute("UPDATE users SET coins=coins+? WHERE user_id=?",(current,int(old_bidder)))
        con.execute("UPDATE auctions SET highest_bidder_id=?,highest_bid=? WHERE auction_id=?",(uid,data.bid,data.auction_id))
        con.execute("INSERT INTO transaction_logs(kind,sender_id,recipient_id,amount,character_id,quantity,details) VALUES(?,?,?,?,?,?,?)",
                    ("auction_bid",uid,int(auction["seller_id"]),data.bid,int(auction["character_id"]),1,f"Auction #{data.auction_id}"))
        con.commit(); return {"ok":True,"message":"Bid accepted. Coins are reserved until outbid or auction settlement."}
    except HTTPException:
        con.rollback(); raise
    except Exception:
        con.rollback(); raise HTTPException(500,"Bid failed safely.")
    finally: con.close()

@app.get("/api/transactions")
def transactions(authorization: Optional[str] = Header(default=None)):
    user=current_user(authorization); uid=int(user["id"])
    if DEMO_MODE: return {"items":[{"kind":"market_buy","amount":8200,"details":"Bought Gojo Satoru","created_at":"Today"},{"kind":"daily","amount":5000,"details":"Daily reward","created_at":"Yesterday"}]}
    con=db()
    try:
        rows=con.execute("""SELECT kind,amount,character_id,quantity,details,created_at
            FROM transaction_logs WHERE sender_id=? OR recipient_id=? ORDER BY id DESC LIMIT 50""",(uid,uid)).fetchall()
        return {"items":[rowdict(r) for r in rows]}
    finally: con.close()
