"""
Paginación personalizada para DRF.
"""
from rest_framework.pagination import PageNumberPagination


class PaginacionEstandar(PageNumberPagination):
    """
    Paginación con 20 items por página.
    Permite que el cliente especifique page_size via query param.
    """

    page_size = 20
    page_size_query_param = "page_size"
    page_size_query_description = "Número de items por página"
    max_page_size = 100


class PaginacionPequeña(PageNumberPagination):
    """
    Paginación con 10 items por página.
    """

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class PaginacionGrande(PageNumberPagination):
    """
    Paginación con 100 items por página.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500
