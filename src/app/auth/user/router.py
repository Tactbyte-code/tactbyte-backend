from fastapi import APIRouter

router = APIRouter(tags=["Auth", "User"])

@router.post("/login")
def admin_login():

    return {
        "access_token":  "access_token",
    }


@router.post("/logout")
def admin_logout():

    return {"message": "Logged out successfully"}


@router.post("/refresh")
def refresh_access_token():
    return {"access_token": "token"}
