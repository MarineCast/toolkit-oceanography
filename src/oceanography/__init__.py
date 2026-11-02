"""Incomplete oceanographic research pipelines; see TODO.txt."""

__version__ = "0.1.0.dev0"


def get_waves(start_date=None, end_date=None, *, study_config=None, **options):
    """Generate the separate Waves product for an explicit approved study."""
    import os
    from .waves import run_waves
    selected = study_config or os.environ.get('MARINECAST_STUDY_CONFIG')
    if selected is None:
        raise ValueError('Supply study_config or MARINECAST_STUDY_CONFIG')
    return run_waves(selected, start_date, end_date, **options)


def check_waves(catalog_path, *, study_config):
    """Read-only exact support, source, schema and scientific reduction checks."""
    from .waves import check_waves as implementation
    return implementation(catalog_path, study_path=study_config)


def get_salishseacast_waves(start_date=None, end_date=None, *, study_config, **options):
    """Separate half-hourly SSC wave nowcasts with source-specific support."""
    from .waves_ssc import run
    return run(study_config, start_date, end_date, **options)


def get_usgs_nearshore_waves(start_date=None, end_date=None, *, study_config, **options):
    """Separate USGS waves; effective-coordinate qualification is required."""
    from .waves_usgs import run
    return run(study_config, start_date, end_date, **options)


def check_regional_waves(catalog_path, *, study_config):
    """Read-only source-specific native/daily/support qualification checks."""
    from .waves_regional import check
    return check(catalog_path, study_path=study_config)
