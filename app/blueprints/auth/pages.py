from flask import Blueprint, redirect, render_template, request

from app.security.session import get_current_user, page_login_required, post_login_path

auth_pages_bp = Blueprint("auth_pages", __name__)


@auth_pages_bp.get("/login")
def login_page():
    destination = post_login_path(request.args.get("next"))
    if get_current_user():
        return redirect(destination)
    return render_template("auth/login.html", post_login_path=destination)


@auth_pages_bp.get("/reset-password")
def reset_password_page():
    return render_template("auth/reset_password.html", mode="reset")


@auth_pages_bp.get("/set-password")
def set_password_page():
    return render_template("auth/reset_password.html", mode="setup")


@auth_pages_bp.get("/account")
@page_login_required
def account_page():
    return render_template("auth/account.html")
