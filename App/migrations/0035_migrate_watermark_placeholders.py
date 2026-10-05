from django.db import migrations


def migrate_watermark_placeholders(apps, schema_editor):
    PhotographerProfile = apps.get_model('App', 'PhotographerProfile')
    legacy = {'ex studio', '© ex studio', 'atelier studio', '© atelier studio', 'studio', '© studio', ''}

    for profile in PhotographerProfile.objects.select_related('user').all():
        current = (profile.watermark_text or '').strip().lower()
        if not current or current in legacy:
            user = getattr(profile, 'user', None)
            full_name = ''
            if user:
                full_name = getattr(user, 'fullname', '') or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            name = full_name.strip() or (profile.name or '').strip() or (getattr(user, 'username', '') if user else '') or 'Photographer'
            profile.watermark_text = f"© {name}"
            profile.save(update_fields=['watermark_text'])

    Gallery = apps.get_model('App', 'Gallery')
    for gallery in Gallery.objects.select_related('photographer', 'photographer__user').all():
        current_g = (gallery.watermark_text or '').strip().lower()
        if current_g in legacy:
            user = getattr(gallery.photographer, 'user', None)
            full_name = ''
            if user:
                full_name = getattr(user, 'fullname', '') or f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
            name = full_name.strip() or (getattr(gallery.photographer, 'name', '') or '').strip() or (getattr(user, 'username', '') if user else '') or 'Photographer'
            gallery.watermark_text = f"© {name}"
            gallery.save(update_fields=['watermark_text'])


class Migration(migrations.Migration):
    dependencies = [
        ('App', '0034_alter_photographerprofile_enable_watermark_and_more'),
    ]
    operations = [
        migrations.RunPython(migrate_watermark_placeholders, reverse_code=migrations.RunPython.noop),
    ]
