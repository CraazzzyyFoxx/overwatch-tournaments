//! Native team-balancing engines behind one calling convention:
//! `run_<engine>(request_json, progress_callback=None) -> response_json`.
//! Requests share `{players, num_teams, seed, roles}` plus an engine-specific
//! `config`; responses share `variants[].teams[{id, roster}]` plus
//! engine-specific `variants[].metrics`.

use pyo3::prelude::*;

mod common;
mod mix;
#[doc(hidden)]
pub mod moo;

/// Tournament engine: multi-objective GA, any number of teams.
#[pyfunction]
#[pyo3(signature = (request_json, progress_callback=None))]
fn run_moo_optimizer(
    py: Python<'_>,
    request_json: &str,
    progress_callback: Option<Py<PyAny>>,
) -> PyResult<String> {
    common::run_json(py, request_json, |request| {
        moo::run(request, progress_callback.as_ref())
    })
}

/// Mix engine: exhaustive search, exactly two teams.
#[pyfunction]
#[pyo3(signature = (request_json, progress_callback=None))]
fn run_mix_balancer(
    py: Python<'_>,
    request_json: &str,
    progress_callback: Option<Py<PyAny>>,
) -> PyResult<String> {
    common::run_json(py, request_json, |request| {
        mix::run(request, progress_callback.as_ref())
    })
}

#[pymodule]
fn balancer_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_moo_optimizer, m)?)?;
    m.add_function(wrap_pyfunction!(run_mix_balancer, m)?)?;
    Ok(())
}
