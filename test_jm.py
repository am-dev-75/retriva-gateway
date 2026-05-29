import sys
sys.path.insert(0, "/home/llandre/devel/ai/retriva/implementation/retriva/src")
from retriva.ingestion_api.job_manager import JobManager

m1 = JobManager()
m1.create_job("foo", "bar")
m2 = JobManager()
print(m2.list_jobs())
