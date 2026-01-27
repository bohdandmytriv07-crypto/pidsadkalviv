from . import common, driver, passenger, profile, chat, rating, admin

routers_list = [
    admin.router,
    common.router,
    profile.router,
    driver.router,
    passenger.router,
    chat.router,
    rating.router
]