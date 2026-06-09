"""Enable PostGIS + a GiST index for fast radius search — Postgres only.

On SQLite (dev/tests) this is a no-op, so nothing breaks. On a Postgres database
it installs the postgis extension and a functional GiST index on the lat/lng
columns that ST_DWithin (apps/marketplace/geo.py) uses.
"""
from django.db import migrations

INDEX = "profiles_creativeprofile_geo_gix"


def enable_postgis(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {INDEX} "
            "ON profiles_creativeprofile "
            "USING gist (geography(ST_MakePoint(longitude, latitude)));"
        )


def drop_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP INDEX IF EXISTS {INDEX};")


class Migration(migrations.Migration):
    dependencies = [("profiles", "0003_creativeprofile_view_count")]
    operations = [migrations.RunPython(enable_postgis, drop_index)]
