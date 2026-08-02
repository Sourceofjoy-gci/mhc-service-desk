from django.db import migrations


CREATE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION protect_ticket_reference_immutable()
RETURNS trigger AS $$
BEGIN
    IF NEW.number IS DISTINCT FROM OLD.number THEN
        RAISE EXCEPTION 'Ticket reference is immutable.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER_SQL = """
CREATE TRIGGER ticket_reference_immutable
BEFORE UPDATE OF number ON ticket
FOR EACH ROW
EXECUTE FUNCTION protect_ticket_reference_immutable();
"""

DROP_TRIGGER_SQL = "DROP TRIGGER IF EXISTS ticket_reference_immutable ON ticket;"
DROP_FUNCTION_SQL = "DROP FUNCTION IF EXISTS protect_ticket_reference_immutable();"


def install_reference_guard(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(CREATE_FUNCTION_SQL)
    schema_editor.execute(DROP_TRIGGER_SQL)
    schema_editor.execute(CREATE_TRIGGER_SQL)


def remove_reference_guard(apps, schema_editor):
    del apps
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DROP_TRIGGER_SQL)
    schema_editor.execute(DROP_FUNCTION_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0011_ticketreferencecounter"),
    ]

    operations = [
        migrations.RunPython(
            install_reference_guard,
            remove_reference_guard,
        ),
    ]
