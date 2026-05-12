from fastapi import APIRouter, HTTPException
from firebase_admin import firestore
from app.models.users import WaitlistEmail
from app.api.endpoints import admin_dixon_coles, billing, clubs, competitions, players, odds, predictions, users

api_router = APIRouter()


@api_router.get("/", tags=["Root"])
async def read_api_root():
    return {"message": "Welcome to the Sharper Bets API"}


# --- END OF NEW ROUTE ---
api_router.include_router(competitions.router, prefix="/competitions", tags=["competitions"])
api_router.include_router(clubs.router, prefix="/clubs", tags=["clubs"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(odds.router, prefix="/odds", tags=["odds"])

#predictions
api_router.include_router(predictions.router, prefix="/predictions", tags=["Dixon-Coles Predictions"])

#users
api_router.include_router(users.router, prefix="/users", tags=["users"])

#billing (LemonSqueezy)
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])

#admin (Dixon-Coles data + training management)
api_router.include_router(
    admin_dixon_coles.router,
    prefix="/admin/dixon-coles",
    tags=["admin · Dixon-Coles"],
)


@api_router.post("/waitlist", tags=["waitlist"])
async def add_to_waitlist(waitlist_email: WaitlistEmail):
    try:
        # Use the Firestore client initialized in main.py via firebase_admin
        db = firestore.client()
        db.collection("waitlist").add({"email": waitlist_email.email})
        return {"message": "Email added to the waitlist!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
