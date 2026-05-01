from fastapi import APIRouter, Depends, HTTPException
from typing import List

# Import the service functions and custom exceptions
from app.services.dixon_coles.dixon_coles_service import (
    ModelNotFoundError,
    TeamNotFoundError,
    DataNotFoundError,
    get_prediction,
    get_teams_for_league,
    list_available_models,
    train_model_for_league
)

# Import Pydantic models
from app.models.predictions import (
    TrainRequest,
    TrainResponse,
    PredictionRequest,
    PredictionResponse,
    TeamListResponse,
)

from app.core.auth import get_current_user, require_role
from app.models.users import User

router = APIRouter()

@router.get("/leagues")
async def get_available_leagues():
    """
    Get list of all available leagues for predictions.
    """
    try:
        leagues = list_available_models()
        return leagues
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving leagues: {str(e)}")

@router.get("/status")
async def get_prediction_status():
    """
    Get the status of the prediction system.
    """
    try:
        models = list_available_models()
        return {
            "status": "operational" if models else "no_models",
            "available_models": len(models),
            "models": models
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")

@router.post("/train", response_model=TrainResponse)
async def train_model(
    request: TrainRequest,
    _admin: User = Depends(require_role("admin")),
):
    """
    Train a Dixon-Coles model for a specific league.
    """
    try:
        result = train_model_for_league(request.league_name, request.force_refit)
        return result
    except DataNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=f"Training failed: {e}")

@router.post("/predict", response_model=PredictionResponse)
async def create_prediction(
    request: PredictionRequest,
    user: User = Depends(get_current_user),
):
    """
    Get a match prediction for two teams in a specific league.
    """
    # Add debugging
    print(f"Received prediction request: {request}")
    print(f"League: {request.league_name}, Home: {request.home_team}, Away: {request.away_team}")
    
    try:
        prediction = get_prediction(request.league_name, request.home_team, request.away_team)
        print(f"Prediction result: {prediction}")
        return prediction
    except ModelNotFoundError as e:
        print(f"ModelNotFoundError: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except TeamNotFoundError as e:
        print(f"TeamNotFoundError: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        print(f"ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@router.get("/models", response_model=List[str])
async def list_models():
    """
    List all currently available (trained) Dixon-Coles models.
    """
    return list_available_models()

@router.get("/teams/{league_name}", response_model=TeamListResponse)
async def list_teams(league_name: str):
    """
    Get a list of all teams available for prediction in a given league's model.
    """
    try:
        teams = get_teams_for_league(league_name)
        return {"league": league_name, "teams": teams}
    except ModelNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/debug")
async def debug_info():
    """
    Get debug information about the prediction system.
    """
    try:
        models = list_available_models()
        return {
            "available_models": models,
            "total_models": len(models),
            "system_status": "operational"
        }
    except Exception as e:
        return {
            "error": str(e),
            "system_status": "error"
        }