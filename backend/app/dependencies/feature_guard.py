from fastapi import Depends, HTTPException
from app.models.user import User
from app.dependencies import get_current_user
from app.core.plan_features import PLAN_FEATURES


def require_feature(feature_name: str):
    def feature_dependency(current_user: User = Depends(get_current_user)):

        # 🔓 Admin / Super Admin bypass
        if current_user.role in ["ADMIN", "SUPER_ADMIN"]:
            return True

        user_plan = current_user.subscription_plan or "BASIC"

        plan_config = PLAN_FEATURES.get(user_plan)

        if not plan_config:
            raise HTTPException(
                status_code=403,
                detail="Invalid subscription plan"
            )

        if not plan_config.get(feature_name, False):
            raise HTTPException(
                status_code=403,
                detail=f"{feature_name} is not available on your plan"
            )

        return True

    return feature_dependency