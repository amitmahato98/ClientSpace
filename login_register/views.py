from django.shortcuts import render


def login_view(request):
    message = "Signed in successfully for this prototype." if request.method == "POST" else ""
    return render(request, "login_register/login.html", {"message": message})


def google_login(request):
    return render(
        request,
        "login_register/login.html",
        {"message": "Google sign-in is available in the full authentication release."},
    )


def register(request):
    message = "Account created for this prototype. No data was saved." if request.method == "POST" else ""
    return render(request, "login_register/register.html", {"message": message})

def forgot_password_view(request):
    message = "Password reset instructions have been sent to your email." if request.method == "POST" else ""
    return render(request, "login_register/forgot_password.html", {"message": message})



# def forgot_password_view(request):
#     return render(request, "login_register/forgot_password.html")


