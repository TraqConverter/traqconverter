from app.database import Base

# Force model imports
import app.models.user
import app.models.project
import app.models.team
import app.models.job
import app.models.credit

print(Base.metadata.tables.keys())