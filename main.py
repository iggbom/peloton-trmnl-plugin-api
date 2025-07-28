from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List
import httpx
from fastapi.responses import FileResponse

app = FastAPI()

PELOTON_BASE = "https://api.onepeloton.com"

# -------------------------------------
# 🔐 Login to Peloton API
# -------------------------------------
async def peloton_login(username: str, password: str) -> httpx.Cookies:
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{PELOTON_BASE}/auth/login", json={
            "username_or_email": username,
            "password": password
        })
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Peloton login failed")
        return client.cookies

# -------------------------------------
# 📆 Streak calculation
# -------------------------------------
# def calculate_streak(workouts: List[dict]) -> int:
#     dates = sorted({
#         datetime.utcfromtimestamp(w["start_time"]).date()
#         for w in workouts if isinstance(w, dict) and isinstance(w.get("start_time"), int)
#     }, reverse=True)

#     today = datetime.utcnow().date()
#     streak = 0
#     for d in dates:
#         if d == today - timedelta(days=streak):
#             streak += 1
#         else:
#             break
#     return streak

def calculate_weekly_streak(workouts: List[dict]) -> int:
    weeks_with_workouts = set()

    for w in workouts:
        ts = w.get("start_time")
        if isinstance(ts, int):
            workout_date = datetime.utcfromtimestamp(ts).date()
            year, week_num, _ = workout_date.isocalendar()
            weeks_with_workouts.add((year, week_num))

    if not weeks_with_workouts:
        return 0

    today = datetime.utcnow().date()
    current_year, current_week, _ = today.isocalendar()

    streak = 0
    y, w = current_year, current_week

    while (y, w) in weeks_with_workouts:
        streak += 1
        if w == 1:
            y -= 1
            w = 52
        else:
            w -= 1

    return streak

# -------------------------------------
# 🧮 Fetch workouts (paginate only as needed)
# -------------------------------------
async def fetch_workouts_for_streak(cookies: httpx.Cookies, user_id: str) -> List[dict]:
    async with httpx.AsyncClient(cookies=cookies) as client:
        workouts = []
        page = 0
        limit = 100

        while True:
            res = await client.get(
                f"{PELOTON_BASE}/api/user/{user_id}/workouts",
                params={"limit": limit, "page": page}
            )
            if res.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Failed to fetch workouts on page {page}")

            data = res.json().get("data", [])
            if not data:
                break

            workouts.extend(data)

            dates = sorted({
                datetime.utcfromtimestamp(w["start_time"]).date()
                for w in workouts if isinstance(w, dict) and "start_time" in w
            }, reverse=True)

            today = datetime.utcnow().date()
            for i, d in enumerate(dates):
                if d != today - timedelta(days=i):
                    return workouts

            page += 1

        return workouts

# -------------------------------------
# 🚀 API Endpoint (with credentials)
# -------------------------------------
class Credentials(BaseModel):
    username: str
    password: str

@app.post("/peloton/summary")
async def peloton_summary(creds: Credentials):
    if not creds.username or not creds.password:
        raise HTTPException(status_code=400, detail="Missing credentials")

    cookies = await peloton_login(creds.username, creds.password)

    # Get user ID and profile
    async with httpx.AsyncClient(cookies=cookies) as client:
        me_res = await client.get(f"{PELOTON_BASE}/api/me")
        if me_res.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to get /me")
        user_id = me_res.json()["id"]

        profile_res = await client.get(f"{PELOTON_BASE}/api/user/{user_id}")
        if profile_res.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to get user profile")

        total_workouts = profile_res.json().get("total_workouts")
        if total_workouts is None:
            raise HTTPException(status_code=500, detail="Could not find total_workouts")

    # Calculate streaks
    workouts = await fetch_workouts_for_streak(cookies, user_id)
    weekly_streak = calculate_weekly_streak(workouts)
    streak_bar = generate_streak_bar(weekly_streak)
    # streak = calculate_streak(workouts)
    last_workout = max(workouts, key=lambda w: w["start_time"])
    last_date = datetime.utcfromtimestamp(last_workout["start_time"]).strftime("%Y-%m-%d")

    return {
        "total_activities": total_workouts,
        "weekly_streak": weekly_streak,
        "last_workout_date": last_date,
        "streak_bar": streak_bar
    }

@app.get("/plugin.json")
def get_plugin_json():
    return FileResponse("plugin.json", media_type="application/json")

def generate_streak_bar(weeks: int, max_units: int = 20) -> str:
    if weeks <= max_units:
        return "●" * weeks
    else:
        return "●" * max_units + f" +{weeks - max_units}"
