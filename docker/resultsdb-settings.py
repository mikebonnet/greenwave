SECRET_KEY = 'resultsdb'
SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2://resultsdb:resultsdb@rdb:5432/resultsdb'
FILE_LOGGING = False
LOGFILE = '/var/log/resultsdb/resultsdb.log'
SYSLOG_LOGGING = False
STREAM_LOGGING = True
RUN_HOST= '0.0.0.0'
RUN_PORT = 5001
MESSAGE_BUS_PUBLISH = False
MESSAGE_BUS_PLUGIN = 'fedmsg'
MESSAGE_BUS_KWARGS = {'modname': 'resultsdb'}
